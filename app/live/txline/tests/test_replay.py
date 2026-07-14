"""Timing, validation, and cancellation tests for TxLINE replay."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.live.txline.replay import TxLineReplaySource


def _write_recording(path: Path, offsets: list[float]) -> None:
    """Write a compact recording with one confirmed shot per timestamp."""
    base_timestamp = 1_752_086_400.0
    lines: list[str] = []
    for index, offset in enumerate(offsets):
        timestamp = base_timestamp + offset
        envelope: dict[str, Any] = {
            "received_at": datetime.fromtimestamp(timestamp, tz=UTC).isoformat(),
            "sse_id": None,
            "sse_event": "historical",
            "data": {
                "FixtureId": 77,
                "Participant1Id": 1,
                "Participant2Id": 2,
                "StatusId": 2,
                "Action": "shot",
                "Id": index + 1,
                "Participant": 1,
                "Confirmed": True,
                "Clock": {"Seconds": index + 1},
                "Data": {"Outcome": "OffTarget"},
            },
        }
        lines.append(json.dumps(envelope))
    path.write_text("\n".join(lines), encoding="utf-8")


async def test_replay_scales_and_caps_inter_frame_delay(tmp_path: Path) -> None:
    recording = tmp_path / "session.jsonl"
    _write_recording(recording, [0.0, 4.0, 1_004.0])
    sleep = AsyncMock()

    with patch("app.live.txline.replay.asyncio.sleep", sleep):
        events = [
            event
            async for event in TxLineReplaySource(tmp_path).stream(
                match_id=77, recording_file=recording.name, speed=2.0
            )
        ]

    assert len(events) == 4  # One synthesized half start plus three shots.
    assert sleep.await_count == 2
    assert sleep.await_args_list[0].args[0] == pytest.approx(2.0, rel=0.05)
    assert sleep.await_args_list[1].args[0] == TxLineReplaySource.MAX_SLEEP_SECONDS


async def test_replay_cancellation_propagates(tmp_path: Path) -> None:
    recording = tmp_path / "session.jsonl"
    _write_recording(recording, [0.0, 5.0])
    stream = TxLineReplaySource(tmp_path).stream(77, recording.name)
    await stream.__anext__()  # Half Start from the first frame.
    await stream.__anext__()  # Shot from the first frame.

    with patch(
        "app.live.txline.replay.asyncio.sleep",
        new=AsyncMock(side_effect=asyncio.CancelledError),
    ):
        with pytest.raises(asyncio.CancelledError):
            await stream.__anext__()


async def test_replay_explicitly_skips_heartbeat_envelopes(tmp_path: Path) -> None:
    """Heartbeat frames never reach phase or football normalization."""
    recording = tmp_path / "heartbeat.jsonl"
    envelope: dict[str, Any] = {
        "received_at": datetime.now(tz=UTC).isoformat(),
        "sse_id": None,
        "sse_event": "heartbeat",
        "data": {
            "FixtureId": 77,
            "StatusId": 2,
            "Action": "goal",
            "Id": 1,
            "Participant": 1,
            "Confirmed": True,
            "Data": {"PlayerId": 9},
        },
    }
    recording.write_text(json.dumps(envelope), encoding="utf-8")

    events = [
        event
        async for event in TxLineReplaySource(tmp_path).stream(
            match_id=77,
            recording_file=recording.name,
        )
    ]

    assert events == []


def test_replay_rejects_paths_outside_recording_root(tmp_path: Path) -> None:
    source = TxLineReplaySource(tmp_path / "allowed")

    with pytest.raises(ValueError, match="inside"):
        source._resolve_recording(str(tmp_path / "outside.jsonl"))
