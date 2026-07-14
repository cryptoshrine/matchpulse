"""Tests for TxLINE REST access, SSE parsing, and reconnection."""

import json
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from pytest import MonkeyPatch
from tenacity import wait_none

from app.core.config import get_settings
from app.live.txline.client import TxLineClient, _iter_sse_frames
from app.live.txline.exceptions import (
    TxLineAuthenticationError,
    TxLineSubscriptionMismatchError,
)
from app.live.txline.schemas import TxLineFixture


def _sse_transport(body: bytes) -> httpx.MockTransport:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={"Content-Type": "text/event-stream"},
        )

    return httpx.MockTransport(handler)


async def _read_sse_frames(body: bytes) -> list[dict[str, Any]]:
    transport = _sse_transport(body)
    async with httpx.AsyncClient(transport=transport) as client:
        async with client.stream("GET", "https://txline.test/stream") as response:
            return [frame async for frame in _iter_sse_frames(response)]


async def test_get_fixtures_success(sample_fixture_data: dict[str, Any]) -> None:
    seen_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return httpx.Response(200, json=[sample_fixture_data])

    client = TxLineClient(transport=httpx.MockTransport(handler))
    fixtures = await client.get_fixtures(competition_id=72, start_epoch_day=20648)

    assert fixtures == [TxLineFixture.model_validate(sample_fixture_data)]
    assert seen_request is not None
    assert seen_request.url.params["competitionId"] == "72"
    assert seen_request.url.params["startEpochDay"] == "20648"


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [(401, TxLineAuthenticationError), (403, TxLineSubscriptionMismatchError)],
)
async def test_get_fixtures_classifies_auth_errors(
    status_code: int,
    error_type: type[Exception],
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code)

    client = TxLineClient(transport=httpx.MockTransport(handler))

    with pytest.raises(error_type):
        await client.get_fixtures()


async def test_scores_snapshot_uses_fixture_path_and_as_of(
    sample_scores_frame_data: dict[str, Any],
) -> None:
    seen_request: httpx.Request | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return httpx.Response(200, json=[sample_scores_frame_data])

    client = TxLineClient(transport=httpx.MockTransport(handler))
    messages = await client.get_scores_snapshot(18237038, as_of=1784056500000)

    assert messages[0].fixtureId == 18237038
    assert seen_request is not None
    assert seen_request.url.path.endswith("/scores/snapshot/18237038")
    assert seen_request.url.params["asOf"] == "1784056500000"


async def test_scores_updates_success(sample_scores_frame_data: dict[str, Any]) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/scores/updates/18237038")
        return httpx.Response(200, json=[sample_scores_frame_data])

    client = TxLineClient(transport=httpx.MockTransport(handler))

    assert len(await client.get_scores_updates(18237038)) == 1


async def test_scores_historical_success(sample_scores_frame_data: dict[str, Any]) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/scores/historical/18237038")
        return httpx.Response(200, json=[sample_scores_frame_data])

    client = TxLineClient(transport=httpx.MockTransport(handler))

    assert len(await client.get_scores_historical(18237038)) == 1


async def test_stat_validation_uses_real_fixture_sequence_and_stat_keys() -> None:
    """Merkle proof requests include all three required query parameters."""
    seen_request: httpx.Request | None = None
    proof = {
        "hashes": ["hash-1"],
        "indices": [0],
        "fixtureProof": ["fixture-proof"],
        "mainTreeProof": ["main-proof"],
        "eventStatRoot": "root",
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_request
        seen_request = request
        return httpx.Response(200, json=proof)

    client = TxLineClient(transport=httpx.MockTransport(handler))
    result = await client.get_stat_validation(
        fixture_id=18237038,
        seq=222,
        stat_keys=["2", "1002"],
    )

    assert result == proof
    assert seen_request is not None
    assert seen_request.url.path.endswith("/scores/stat-validation-v3")
    assert seen_request.url.params["fixtureId"] == "18237038"
    assert seen_request.url.params["seq"] == "222"
    assert seen_request.url.params["statKeys"] == "2,1002"


@pytest.mark.parametrize(
    ("seq", "stat_keys"),
    [(0, ["2"]), (222, []), (222, ["1", "2", "3", "4", "5", "6"])],
)
async def test_stat_validation_rejects_invalid_proof_coordinates(
    seq: int,
    stat_keys: list[str],
) -> None:
    """Fabricated sequences and unsupported key counts fail before HTTP."""
    client = TxLineClient()

    with pytest.raises(ValueError):
        await client.get_stat_validation(18237038, seq, stat_keys)


async def test_scores_historical_decodes_finite_sse(
    sample_scores_frame_data: dict[str, Any],
) -> None:
    """Historical responses use SSE content type despite being finite."""
    body = f"event: score\ndata: {json.dumps(sample_scores_frame_data)}\n\n".encode()

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={"Content-Type": "text/event-stream"},
        )

    client = TxLineClient(transport=httpx.MockTransport(handler))

    messages = await client.get_scores_historical(18237038)

    assert len(messages) == 1
    assert messages[0].fixtureId == 18237038


async def test_missing_credentials_fail_before_transport(
    monkeypatch: MonkeyPatch,
) -> None:
    call_count = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=[])

    monkeypatch.setenv("TXLINE_GUEST_JWT", "")
    get_settings.cache_clear()
    client = TxLineClient(transport=httpx.MockTransport(handler))

    with pytest.raises(TxLineAuthenticationError, match="credentials are not configured"):
        await client.get_fixtures()
    assert call_count == 0


async def test_sse_parser_decodes_complete_multiline_block() -> None:
    frames = await _read_sse_frames(
        b'id: 123:1\nevent: score\ndata: {"fixtureId": 18237038,\ndata: "seq": 1}\n\n'
    )

    assert frames == [
        {
            "id": "123:1",
            "event": "score",
            "data": {"fixtureId": 18237038, "seq": 1},
        }
    ]


async def test_sse_parser_yields_heartbeat() -> None:
    frames = await _read_sse_frames(b"event: heartbeat\ndata: {}\n\n")

    assert frames[0]["event"] == "heartbeat"
    assert frames[0]["data"] == {}


async def test_sse_parser_ignores_comments_and_flushes_at_eof() -> None:
    frames = await _read_sse_frames(b': keep-alive\nid: final\ndata: {"ok": true}')

    assert frames == [{"id": "final", "event": "message", "data": {"ok": True}}]


async def test_sse_parser_preserves_malformed_json() -> None:
    frames = await _read_sse_frames(b"event: score\ndata: not-json\n\n")

    assert frames[0]["data"] == "not-json"


@pytest.mark.parametrize("connection_error", [httpx.ConnectError, httpx.ConnectTimeout])
async def test_stream_scores_reconnects_after_connection_failure(
    connection_error: type[httpx.RequestError],
) -> None:
    call_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise connection_error("temporary failure", request=request)
        return httpx.Response(200, content=b"id: resumed\nevent: score\ndata: {}\n\n")

    client = TxLineClient(transport=httpx.MockTransport(handler))
    with patch("app.live.txline.client.wait_exponential", return_value=wait_none()):
        stream = client.stream_scores()
        frame = await stream.__anext__()
        await stream.aclose()

    assert frame["id"] == "resumed"
    assert call_count == 2


async def test_stream_scores_passes_last_event_id_header() -> None:
    seen_header: str | None = None

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_header
        seen_header = request.headers.get("Last-Event-ID")
        return httpx.Response(200, content=b"event: heartbeat\ndata: {}\n\n")

    client = TxLineClient(transport=httpx.MockTransport(handler))
    stream = client.stream_scores(last_event_id="cursor-9")
    await stream.__anext__()
    await stream.aclose()

    assert seen_header == "cursor-9"


async def test_stream_scores_yields_heartbeat_run() -> None:
    body = b"event: heartbeat\ndata: {}\n\nevent: heartbeat\ndata: {}\n\n"
    client = TxLineClient(transport=_sse_transport(body))
    stream = client.stream_scores()

    frames = [await stream.__anext__(), await stream.__anext__()]
    await stream.aclose()

    assert [frame["event"] for frame in frames] == ["heartbeat", "heartbeat"]


async def test_rest_endpoint_rejects_non_list_payload() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "object"})

    client = TxLineClient(transport=httpx.MockTransport(handler))

    with pytest.raises(ValueError, match="non-list"):
        await client.get_fixtures()
