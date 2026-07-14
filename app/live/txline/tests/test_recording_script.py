"""Tests for recording CLI sidecar helpers."""

import json
from pathlib import Path
from typing import Any

from app.live.txline.schemas import TxLineFixture
from scripts.record_txline_session import _load_sidecar_metadata, _write_sidecar


class FakeFixtureClient:
    """Fixture snapshot provider used by sidecar tests."""

    def __init__(self, fixtures: list[TxLineFixture], error: Exception | None = None) -> None:
        self.fixtures = fixtures
        self.error = error

    async def get_fixtures(self) -> list[TxLineFixture]:
        if self.error is not None:
            raise self.error
        return self.fixtures


async def test_load_sidecar_metadata_for_fixture(sample_fixture_data: dict[str, Any]) -> None:
    fixture = TxLineFixture.model_validate(sample_fixture_data)

    metadata = await _load_sidecar_metadata(FakeFixtureClient([fixture]), fixture.FixtureId)

    assert metadata is not None
    assert metadata["fixture_id"] == fixture.FixtureId
    assert metadata["participant1"] == "France"


async def test_load_sidecar_metadata_failure_is_non_fatal() -> None:
    metadata = await _load_sidecar_metadata(FakeFixtureClient([], RuntimeError("offline")), None)

    assert metadata is None


def test_write_sidecar_next_to_recording(tmp_path: Path) -> None:
    recording_path = tmp_path / "all_20260714_180000.jsonl"

    _write_sidecar(recording_path, {"fixtures": []})

    sidecar_path = Path(f"{recording_path}.meta.json")
    assert json.loads(sidecar_path.read_text(encoding="utf-8")) == {"fixtures": []}
