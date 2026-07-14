"""Crash-safe JSONL recording and REST-fallback conversion for TxLINE."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.live.txline.client import TxLineClient
from app.live.txline.schemas import TxLineScoresMessage

logger = get_logger(__name__)

DEFAULT_RECORDING_DIR = Path("data/txline_recordings")


def _frame_to_envelope(frame: dict[str, Any]) -> dict[str, Any]:
    """Convert one live SSE frame into the canonical recording envelope.

    Args:
        frame: Parsed SSE frame from :meth:`TxLineClient.stream_scores`.

    Returns:
        Four-key replay envelope shared by live and REST capture paths.
    """
    return {
        "received_at": datetime.now(UTC).isoformat(),
        "sse_id": frame.get("id"),
        "sse_event": frame.get("event"),
        "data": frame.get("data"),
    }


class TxLineSessionRecorder:
    """Append a TxLINE scores stream to a flush-per-frame JSONL session."""

    def __init__(
        self,
        client: TxLineClient,
        output_dir: Path = DEFAULT_RECORDING_DIR,
    ) -> None:
        """Initialize a recorder and create its output directory.

        Args:
            client: Authenticated TxLINE client providing the score stream.
            output_dir: Directory in which session files are created.
        """
        self._client = client
        self._output_dir = output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._frame_count = 0
        self._file_path: Path | None = None

    @property
    def frame_count(self) -> int:
        """Return the number of frames durably written in this session."""
        return self._frame_count

    @property
    def file_path(self) -> Path | None:
        """Return the active recording path, if recording has started."""
        return self._file_path

    def _new_output_path(self, fixture_id: int | None) -> Path:
        """Create a timestamped output path for a fixture or all fixtures.

        Args:
            fixture_id: Specific fixture identifier, or ``None`` for all scores.

        Returns:
            New JSONL path below the configured output directory.
        """
        fixture_label = str(fixture_id) if fixture_id is not None else "all"
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        return self._output_dir / f"{fixture_label}_{timestamp}.jsonl"

    async def record(self, fixture_id: int | None = None) -> None:
        """Record scores frames until cancelled or the source terminates.

        Args:
            fixture_id: Optional fixture filter; ``None`` records every score frame.
        """
        self._file_path = self._new_output_path(fixture_id)
        self._frame_count = 0
        logger.info(
            "live.txline.recorder_started",
            fixture_id=fixture_id,
            output_path=str(self._file_path),
        )

        with self._file_path.open("a", encoding="utf-8") as handle:
            async for frame in self._client.stream_scores(fixture_id=fixture_id):
                envelope = _frame_to_envelope(frame)
                handle.write(json.dumps(envelope) + "\n")
                handle.flush()
                self._frame_count += 1
                logger.debug(
                    "live.txline.recorder_frame_written",
                    fixture_id=fixture_id,
                    frame_count=self._frame_count,
                )


def convert_scores_to_envelopes(
    messages: list[TxLineScoresMessage],
    source: str,
) -> list[dict[str, Any]]:
    """Convert REST scores messages to canonical replay envelopes.

    Args:
        messages: Validated messages from scores updates or historical REST calls.
        source: Provenance label such as ``historical`` or ``updates``.

    Returns:
        Envelopes with the same four top-level keys as live recordings.
    """
    return [
        {
            "received_at": _message_received_at(message),
            "sse_id": None,
            "sse_event": source,
            "data": message.model_dump(mode="json"),
        }
        for message in messages
    ]


def _message_received_at(message: TxLineScoresMessage) -> str:
    """Return a replay timestamp derived from a provider message.

    Historical TxLINE responses carry epoch-millisecond ``Ts`` values. Using
    those values preserves match timing in recovered recordings instead of
    collapsing every frame onto the converter's wall-clock timestamp.

    Args:
        message: Historical or updates score message.

    Returns:
        Timezone-aware ISO timestamp suitable for replay delay calculation.
    """
    timestamp = message.ts
    if timestamp is None and message.model_extra is not None:
        raw_timestamp = message.model_extra.get("Ts")
        if isinstance(raw_timestamp, int):
            timestamp = raw_timestamp
    if timestamp is None:
        return datetime.now(UTC).isoformat()
    return datetime.fromtimestamp(timestamp / 1000, tz=UTC).isoformat()


def write_envelopes_to_jsonl(
    envelopes: list[dict[str, Any]],
    output_path: Path,
) -> None:
    """Write canonical envelopes to a replacement JSONL file.

    Args:
        envelopes: Replay envelopes to serialize.
        output_path: Destination file; its parent directories are created.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for envelope in envelopes:
            handle.write(json.dumps(envelope) + "\n")

    logger.info(
        "live.txline.envelopes_written",
        output_path=str(output_path),
        count=len(envelopes),
    )
