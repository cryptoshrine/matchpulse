"""Replay TxLINE JSONL recordings through the live-event contract."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from app.core.logging import get_logger
from app.live.schemas import LiveEventFrame
from app.live.txline.normalizer import TxLineNormalizer
from app.live.txline.recorder import DEFAULT_RECORDING_DIR

logger = get_logger(__name__)


class TxLineReplaySource:
    """Yield normalized events from one canonical TxLINE recording."""

    MAX_SLEEP_SECONDS: float = 5.0

    def __init__(self, recordings_dir: Path = DEFAULT_RECORDING_DIR) -> None:
        """Initialize the replay source with its allowed filesystem root.

        Args:
            recordings_dir: Directory recordings must resolve beneath.
        """
        self._recordings_dir = recordings_dir.resolve()

    async def stream(
        self,
        match_id: int,
        recording_file: str,
        speed: float = 1.0,
    ) -> AsyncIterator[LiveEventFrame]:
        """Replay normalized events with scaled, capped inter-event delays.

        Args:
            match_id: Fixture identifier used by downstream state.
            recording_file: Bare filename or resolved path under recordings_dir.
            speed: Playback multiplier; must be positive.

        Yields:
            Normalized phase and football events.

        Raises:
            ValueError: If speed is invalid or the path escapes recordings_dir.
            FileNotFoundError: If the recording does not exist.
        """
        if speed <= 0:
            raise ValueError("Replay speed must be greater than zero")
        path = self._resolve_recording(recording_file)
        lines = path.read_text(encoding="utf-8").splitlines()
        normalizer = TxLineNormalizer(match_id=match_id)
        previous_received_at: datetime | None = None
        emitted_count = 0

        logger.info(
            "live.txline.replay.started",
            match_id=match_id,
            recording_file=path.name,
            speed=speed,
            frame_count=len(lines),
        )

        for line_number, line in enumerate(lines, start=1):
            try:
                parsed: Any = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "live.txline.replay.line_skipped",
                    match_id=match_id,
                    recording_file=path.name,
                    line_number=line_number,
                    reason="invalid_json",
                    error=str(exc),
                )
                continue
            if not isinstance(parsed, dict):
                continue
            envelope = cast(dict[str, Any], parsed)
            if envelope.get("sse_event") == "heartbeat":
                continue
            raw = envelope.get("data")
            if not isinstance(raw, dict):
                continue
            typed_raw = cast(dict[str, Any], raw)
            raw_match_id = typed_raw.get("FixtureId", typed_raw.get("fixtureId"))
            if isinstance(raw_match_id, int) and raw_match_id != match_id:
                continue

            received_at = self._parse_received_at(envelope.get("received_at"))
            if previous_received_at is not None and received_at is not None:
                delay = min(
                    max((received_at - previous_received_at).total_seconds(), 0.0) / speed,
                    self.MAX_SLEEP_SECONDS,
                )
                if delay > 0:
                    await asyncio.sleep(delay)
            if received_at is not None:
                previous_received_at = received_at

            events = normalizer.to_phase_events(typed_raw)
            normalized = normalizer.to_event_frame(typed_raw)
            if normalized is not None:
                events.append(normalized)
            if not events:
                continue

            for event in events:
                emitted_count += 1
                yield event

        logger.info(
            "live.txline.replay.completed",
            match_id=match_id,
            recording_file=path.name,
            events_emitted=emitted_count,
        )

    def _resolve_recording(self, recording_file: str) -> Path:
        """Resolve a recording path and enforce the configured root."""
        candidate = Path(recording_file)
        if not candidate.is_absolute():
            candidate = self._recordings_dir / candidate
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self._recordings_dir):
            raise ValueError("Recording path must stay inside the TxLINE recordings directory")
        if not resolved.is_file():
            raise FileNotFoundError(f"TxLINE recording not found: {resolved.name}")
        return resolved

    @staticmethod
    def _parse_received_at(value: Any) -> datetime | None:
        """Parse a canonical envelope timestamp, returning None on bad input."""
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
