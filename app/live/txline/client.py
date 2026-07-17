"""Async REST and Server-Sent Events client for TxLINE."""

import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, cast

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, wait_exponential

from app.core.config import get_settings
from app.core.logging import get_logger
from app.live.exceptions import LiveApiConnectionError
from app.live.txline.auth import build_txline_headers, raise_for_txline_auth_error
from app.live.txline.exceptions import (
    TxLineAuthenticationError,
    TxLineError,
    TxLineStreamEndedError,
)
from app.live.txline.schemas import TxLineFixture, TxLineScoresMessage

if TYPE_CHECKING:
    from app.live.schemas import LiveEventFrame

logger = get_logger(__name__)


def _decode_sse_data(data_lines: list[str]) -> Any:
    """Decode one SSE event's accumulated data lines.

    Args:
        data_lines: Values collected from one or more ``data:`` lines.

    Returns:
        Parsed JSON when valid, otherwise the original joined string.
    """
    raw_data = "\n".join(data_lines)
    try:
        return json.loads(raw_data)
    except json.JSONDecodeError:
        return raw_data


async def _iter_sse_frames(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    """Parse a streamed HTTP response into TxLINE SSE frames.

    Args:
        response: Streaming HTTP response from ``/scores/stream``.

    Yields:
        Dictionaries containing ``id``, ``event``, and parsed ``data``.
    """
    event_id: str | None = None
    event_type: str | None = None
    data_lines: list[str] = []

    async for line in response.aiter_lines():
        if line == "":
            if data_lines:
                yield {
                    "id": event_id,
                    "event": event_type or "message",
                    "data": _decode_sse_data(data_lines),
                }
            event_id = None
            event_type = None
            data_lines = []
            continue

        if line.startswith(":"):
            continue
        if line.startswith("id:"):
            event_id = line[3:].lstrip()
        elif line.startswith("event:"):
            event_type = line[6:].lstrip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())

    if data_lines:
        yield {
            "id": event_id,
            "event": event_type or "message",
            "data": _decode_sse_data(data_lines),
        }


def _decode_sse_payload_text(payload: str) -> list[object]:
    """Decode a finite SSE response body into its data payloads.

    TxLINE's historical scores endpoint returns ``text/event-stream`` even
    though its OpenAPI description advertises a JSON array. Supporting both
    formats keeps the recovery path compatible with the observed API.

    Args:
        payload: Complete SSE response body.

    Returns:
        Parsed values from every non-empty SSE ``data:`` block.
    """
    decoded: list[object] = []
    data_lines: list[str] = []

    for line in [*payload.splitlines(), ""]:
        if line == "":
            if data_lines:
                decoded.append(_decode_sse_data(data_lines))
                data_lines = []
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())

    return decoded


class TxLineClient:
    """Client for authenticated TxLINE REST and scores-stream operations."""

    DEFAULT_TIMEOUT: float = 30.0

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        """Initialize the client from centralized application settings.

        Args:
            transport: Optional async HTTP transport used by isolated tests.
        """
        settings = get_settings()
        self._base_url = settings.txline_api_base_url.rstrip("/")
        self._guest_jwt = settings.txline_guest_jwt
        self._api_token = settings.txline_api_token
        self._network = settings.txline_network
        self._transport = transport

        logger.info(
            "live.txline.client_initialized",
            base_url=self._base_url,
            network=self._network,
        )

    @property
    def has_credentials(self) -> bool:
        """Return whether both required TxLINE credentials are configured."""
        return bool(self._guest_jwt and self._api_token)

    def _headers(self, *, accept_sse: bool = False) -> dict[str, str]:
        """Build authenticated request headers, rejecting missing credentials.

        Args:
            accept_sse: Include SSE content-negotiation and cache headers.

        Returns:
            Headers ready for a TxLINE request.

        Raises:
            TxLineAuthenticationError: If either credential is empty or missing.
        """
        if not self._guest_jwt or not self._api_token:
            logger.error("live.txline.credentials_missing", network=self._network)
            raise TxLineAuthenticationError(
                "TxLINE credentials are not configured. Complete Task 0 and set "
                "TXLINE_GUEST_JWT and TXLINE_API_TOKEN."
            )
        return build_txline_headers(
            self._guest_jwt,
            self._api_token,
            accept_sse=accept_sse,
        )

    async def _get_json_list(
        self,
        path: str,
        *,
        params: dict[str, int] | None = None,
    ) -> list[object]:
        """Execute one authenticated REST GET returning a JSON array.

        Args:
            path: API path relative to the configured TxLINE base URL.
            params: Optional integer query parameters.

        Returns:
            Raw response items ready for Pydantic validation.

        Raises:
            ValueError: If the endpoint does not return a JSON array.
            httpx.HTTPStatusError: For non-authentication HTTP failures.
        """
        headers = self._headers()
        async with httpx.AsyncClient(
            timeout=self.DEFAULT_TIMEOUT,
            transport=self._transport,
        ) as client:
            response = await client.get(
                f"{self._base_url}/{path.lstrip('/')}",
                headers=headers,
                params=params,
            )
        raise_for_txline_auth_error(response)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if content_type.lower().startswith("text/event-stream"):
            payload: object = _decode_sse_payload_text(response.text)
        else:
            payload = response.json()
        if not isinstance(payload, list):
            raise ValueError(f"TxLINE endpoint {path!r} returned a non-list payload")
        return cast(list[object], payload)

    async def get_fixtures(
        self,
        competition_id: int | None = None,
        start_epoch_day: int | None = None,
    ) -> list[TxLineFixture]:
        """Fetch the fixture snapshot, optionally filtered by competition/day.

        Args:
            competition_id: Optional TxLINE competition identifier.
            start_epoch_day: Optional provider epoch-day filter.

        Returns:
            Validated fixture records.
        """
        params: dict[str, int] = {}
        if competition_id is not None:
            params["competitionId"] = competition_id
        if start_epoch_day is not None:
            params["startEpochDay"] = start_epoch_day

        logger.info(
            "live.txline.fixtures_request_started",
            competition_id=competition_id,
            start_epoch_day=start_epoch_day,
        )
        payload = await self._get_json_list("fixtures/snapshot", params=params or None)
        fixtures = [TxLineFixture.model_validate(item) for item in payload]
        logger.info("live.txline.fixtures_request_completed", count=len(fixtures))
        return fixtures

    async def get_scores_snapshot(
        self,
        fixture_id: int,
        as_of: int | None = None,
    ) -> list[TxLineScoresMessage]:
        """Fetch the current scores snapshot for a fixture.

        Args:
            fixture_id: TxLINE fixture identifier placed in the URL path.
            as_of: Optional provider timestamp for a point-in-time snapshot.

        Returns:
            Validated raw scores messages.
        """
        params = {"asOf": as_of} if as_of is not None else None
        logger.info("live.txline.scores_snapshot_request_started", fixture_id=fixture_id)
        payload = await self._get_json_list(
            f"scores/snapshot/{fixture_id}",
            params=params,
        )
        messages = [TxLineScoresMessage.model_validate(item) for item in payload]
        logger.info(
            "live.txline.scores_snapshot_request_completed",
            fixture_id=fixture_id,
            count=len(messages),
        )
        return messages

    async def get_scores_updates(self, fixture_id: int) -> list[TxLineScoresMessage]:
        """Fetch accumulated scores updates for a fixture.

        Args:
            fixture_id: TxLINE fixture identifier placed in the URL path.

        Returns:
            Validated raw scores messages.
        """
        logger.info("live.txline.scores_updates_request_started", fixture_id=fixture_id)
        payload = await self._get_json_list(f"scores/updates/{fixture_id}")
        messages = [TxLineScoresMessage.model_validate(item) for item in payload]
        logger.info(
            "live.txline.scores_updates_request_completed",
            fixture_id=fixture_id,
            count=len(messages),
        )
        return messages

    async def get_scores_historical(self, fixture_id: int) -> list[TxLineScoresMessage]:
        """Fetch historical scores messages for recovery after a missed recording.

        TxLINE exposes this endpoint from six hours through two weeks after
        kickoff.

        Args:
            fixture_id: TxLINE fixture identifier placed in the URL path.

        Returns:
            Validated raw historical scores messages.
        """
        logger.info("live.txline.historical_request_started", fixture_id=fixture_id)
        payload = await self._get_json_list(f"scores/historical/{fixture_id}")
        messages = [TxLineScoresMessage.model_validate(item) for item in payload]
        logger.info(
            "live.txline.historical_request_completed",
            fixture_id=fixture_id,
            count=len(messages),
        )
        return messages

    async def get_stat_validation(
        self,
        fixture_id: int,
        seq: int,
        stat_keys: list[str],
    ) -> dict[str, Any]:
        """Fetch a TxLINE Merkle multiproof for one recorded score revision.

        Args:
            fixture_id: Real TxLINE fixture identifier from the event frame.
            seq: Real provider sequence from that exact frame; must be positive.
            stat_keys: One to five stat-major keys present in the frame's Stats map.

        Returns:
            Opaque multiproof payload from ``stat-validation-v3``.

        Raises:
            ValueError: If proof coordinates are invalid or response is not an object.
            TxLineAuthenticationError: If credentials are missing or expired.
            httpx.HTTPStatusError: For other HTTP failures.
        """
        if seq < 1:
            raise ValueError("TxLINE proof sequence must be a real positive frame Seq")
        if not 1 <= len(stat_keys) <= 5:
            raise ValueError("TxLINE proof requires between one and five stat keys")

        logger.info(
            "live.txline.stat_validation_request_started",
            fixture_id=fixture_id,
            seq=seq,
            stat_keys=stat_keys,
        )
        headers = self._headers()
        async with httpx.AsyncClient(
            timeout=self.DEFAULT_TIMEOUT,
            transport=self._transport,
        ) as client:
            response = await client.get(
                f"{self._base_url}/scores/stat-validation-v3",
                headers=headers,
                params={
                    "fixtureId": fixture_id,
                    "seq": seq,
                    "statKeys": ",".join(stat_keys),
                },
            )
        raise_for_txline_auth_error(response)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("TxLINE stat-validation-v3 returned a non-object payload")
        proof = {str(key): value for key, value in cast(dict[object, Any], payload).items()}
        logger.info(
            "live.txline.stat_validation_request_completed",
            fixture_id=fixture_id,
            seq=seq,
            stat_keys=stat_keys,
        )
        return proof

    async def subscribe_to_match(
        self,
        match_id: int,
        *,
        auto_reconnect: bool = True,
    ) -> AsyncIterator["LiveEventFrame"]:
        """Yield normalized events for one TxLINE fixture.

        This adapter intentionally matches
        :meth:`StatsBombLiveClient.subscribe_to_match` so the shared live
        subscription manager can switch providers without changing downstream
        processing.

        Args:
            match_id: TxLINE fixture identifier.
            auto_reconnect: Documents the shared client contract. TxLINE's
                underlying SSE iterator always reconnects after transient loss.

        Yields:
            Provider-neutral live event frames.

        Raises:
            LiveApiConnectionError: If TxLINE fails outside its reconnect loop.
        """
        from app.live.schemas import LiveEventFrame
        from app.live.txline.normalizer import TxLineNormalizer

        logger.info(
            "live.txline.subscription_started",
            match_id=match_id,
            auto_reconnect=auto_reconnect,
        )
        normalizer = TxLineNormalizer(match_id=match_id)

        # The live SSE stream (/scores/stream) never carries Lineups, so without
        # this every live event resolves player_id/team_id to None and surfaces
        # raw IDs instead of names ("Lautaro Martínez"). Prime the name maps from
        # a REST snapshot (falling back to the heavier updates pull if the
        # snapshot omits lineups) before streaming. Best-effort by design —
        # naming is enrichment; the live stream must not depend on it. Replays are
        # unaffected: their recovery files already carry lineups in-stream.
        try:
            primed = await self.get_scores_snapshot(match_id)
            learned = normalizer.prime_lineups(message.model_dump() for message in primed)
            if learned == 0:
                primed = await self.get_scores_updates(match_id)
                learned = normalizer.prime_lineups(message.model_dump() for message in primed)
            logger.info(
                "live.txline.lineup_prime_completed",
                match_id=match_id,
                names_learned=learned,
            )
        except (TxLineError, httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "live.txline.lineup_prime_failed",
                match_id=match_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )

        try:
            async for frame in self.stream_scores(fixture_id=match_id):
                if frame.get("event") == "heartbeat":
                    continue
                raw = frame.get("data")
                if not isinstance(raw, dict):
                    logger.warning(
                        "live.txline.subscription_frame_skipped",
                        match_id=match_id,
                        reason="non_object_data",
                    )
                    continue
                typed_raw = cast(dict[str, Any], raw)

                for phase_event in normalizer.to_phase_events(typed_raw):
                    yield phase_event

                event: LiveEventFrame | None = normalizer.to_event_frame(typed_raw)
                if event is not None:
                    yield event
        except (TxLineError, httpx.HTTPError, ValueError) as exc:
            logger.error(
                "live.txline.subscription_failed",
                match_id=match_id,
                error=str(exc),
                error_type=type(exc).__name__,
                exc_info=True,
            )
            raise LiveApiConnectionError(
                f"TxLINE subscription failed for fixture {match_id}: {exc}"
            ) from exc

    async def stream_scores(
        self,
        fixture_id: int | None = None,
        *,
        last_event_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield scores frames continuously, reconnecting after transient loss.

        Args:
            fixture_id: Optional fixture filter; ``None`` subscribes to all scores.
            last_event_id: Optional initial SSE cursor for best-effort resume.

        Yields:
            Parsed TxLINE SSE frames. Heartbeats are deliberately passed through.
        """
        url = f"{self._base_url}/scores/stream"
        params = {"fixtureId": fixture_id} if fixture_id is not None else None
        retryable_errors = (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadError,
            httpx.RemoteProtocolError,
            TxLineStreamEndedError,
        )

        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type(retryable_errors),
            wait=wait_exponential(multiplier=1, min=2, max=30),
            before_sleep=lambda retry_state: logger.warning(
                "live.txline.stream_reconnecting",
                fixture_id=fixture_id,
                attempt=retry_state.attempt_number,
            ),
            reraise=True,
        ):
            with attempt:
                headers = self._headers(accept_sse=True)
                if last_event_id:
                    headers["Last-Event-ID"] = last_event_id

                timeout = httpx.Timeout(connect=10.0, read=None, write=10.0, pool=5.0)
                async with httpx.AsyncClient(
                    timeout=timeout,
                    transport=self._transport,
                ) as client:
                    async with client.stream(
                        "GET",
                        url,
                        headers=headers,
                        params=params,
                    ) as response:
                        raise_for_txline_auth_error(response)
                        response.raise_for_status()
                        logger.info(
                            "live.txline.stream_connected",
                            fixture_id=fixture_id,
                            resumed=last_event_id is not None,
                        )

                        async for frame in _iter_sse_frames(response):
                            if frame["event"] == "heartbeat":
                                logger.debug(
                                    "live.txline.heartbeat_received",
                                    fixture_id=fixture_id,
                                )
                            else:
                                logger.debug(
                                    "live.txline.frame_received",
                                    fixture_id=fixture_id,
                                    sse_event=frame["event"],
                                    sse_id=frame["id"],
                                )
                            frame_id = frame.get("id")
                            if isinstance(frame_id, str) and frame_id:
                                last_event_id = frame_id
                            yield frame

                raise TxLineStreamEndedError(
                    f"TxLINE scores stream ended for fixture {fixture_id}; reconnecting"
                )
