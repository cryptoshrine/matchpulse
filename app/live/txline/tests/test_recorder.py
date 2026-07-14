"""Tests for crash-safe TxLINE recording and REST conversion."""

import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import mock_open, patch

from app.live.txline.recorder import (
    TxLineSessionRecorder,
    convert_scores_to_envelopes,
    write_envelopes_to_jsonl,
)
from app.live.txline.schemas import TxLineScoresMessage


class FakeTxLineClient:
    """Finite scores source used by recorder unit tests."""

    def __init__(self, frames: list[dict[str, Any]]) -> None:
        self.frames = frames

    async def stream_scores(self, fixture_id: int | None = None):
        for frame in self.frames:
            yield frame


def _frames() -> list[dict[str, Any]]:
    return [
        {"id": "1", "event": "score", "data": {"seq": 1}},
        {"id": "2", "event": "heartbeat", "data": {}},
        {"id": "3", "event": "score", "data": {"seq": 2}},
    ]


async def test_record_writes_one_canonical_line_per_frame(tmp_path: Path) -> None:
    recorder = TxLineSessionRecorder(FakeTxLineClient(_frames()), output_dir=tmp_path)

    await recorder.record(fixture_id=123)

    assert recorder.file_path is not None
    lines = recorder.file_path.read_text(encoding="utf-8").splitlines()
    envelopes = [json.loads(line) for line in lines]
    assert len(envelopes) == 3
    assert recorder.frame_count == 3
    assert all(
        set(envelope) == {"received_at", "sse_id", "sse_event", "data"} for envelope in envelopes
    )


async def test_recording_filename_uses_fixture_id(tmp_path: Path) -> None:
    recorder = TxLineSessionRecorder(FakeTxLineClient([]), output_dir=tmp_path)

    await recorder.record(fixture_id=123)

    assert recorder.file_path is not None
    assert re.fullmatch(r"123_\d{8}_\d{6}\.jsonl", recorder.file_path.name)


async def test_recording_filename_uses_all_label(tmp_path: Path) -> None:
    recorder = TxLineSessionRecorder(FakeTxLineClient([]), output_dir=tmp_path)

    await recorder.record()

    assert recorder.file_path is not None
    assert re.fullmatch(r"all_\d{8}_\d{6}\.jsonl", recorder.file_path.name)


async def test_recorder_flushes_every_frame(tmp_path: Path) -> None:
    recorder = TxLineSessionRecorder(FakeTxLineClient(_frames()), output_dir=tmp_path)
    opened = mock_open()

    with patch.object(Path, "open", opened):
        await recorder.record(fixture_id=123)

    assert opened.return_value.flush.call_count == 3


def test_convert_scores_to_envelopes(sample_scores_frame_data: dict[str, Any]) -> None:
    messages = [
        TxLineScoresMessage.model_validate(sample_scores_frame_data),
        TxLineScoresMessage.model_validate({**sample_scores_frame_data, "seq": 13}),
    ]

    envelopes = convert_scores_to_envelopes(messages, "historical")

    assert len(envelopes) == 2
    assert all(envelope["sse_id"] is None for envelope in envelopes)
    assert all(envelope["sse_event"] == "historical" for envelope in envelopes)
    assert envelopes[0]["data"] == messages[0].model_dump(mode="json")
    assert envelopes[0]["received_at"] == envelopes[1]["received_at"]


async def test_live_and_rest_envelope_formats_match(
    tmp_path: Path,
    sample_scores_frame_data: dict[str, Any],
) -> None:
    recorder = TxLineSessionRecorder(FakeTxLineClient(_frames()[:1]), output_dir=tmp_path)
    await recorder.record(fixture_id=123)
    assert recorder.file_path is not None
    live_envelope = json.loads(recorder.file_path.read_text(encoding="utf-8").splitlines()[0])

    messages = [TxLineScoresMessage.model_validate(sample_scores_frame_data)]
    rest_envelopes = convert_scores_to_envelopes(messages, "historical")
    output_path = tmp_path / "fallback" / "historical.jsonl"
    write_envelopes_to_jsonl(rest_envelopes, output_path)
    rest_envelope = json.loads(output_path.read_text(encoding="utf-8").splitlines()[0])

    assert (
        set(rest_envelope)
        == set(live_envelope)
        == {
            "received_at",
            "sse_id",
            "sse_event",
            "data",
        }
    )


def test_recorder_creates_nested_output_directory(tmp_path: Path) -> None:
    nested = tmp_path / "nested" / "dir"

    TxLineSessionRecorder(FakeTxLineClient([]), output_dir=nested)

    assert nested.is_dir()
