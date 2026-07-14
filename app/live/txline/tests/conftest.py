"""Shared fixtures for TxLINE pipeline tests."""

from collections.abc import Iterator
from typing import Any

import pytest
from pytest import MonkeyPatch

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def mock_txline_credentials(monkeypatch: MonkeyPatch) -> Iterator[None]:
    """Configure isolated TxLINE credentials for every unit test."""
    monkeypatch.setenv("TXLINE_ENABLED", "true")
    monkeypatch.setenv("TXLINE_GUEST_JWT", "test_guest_jwt")
    monkeypatch.setenv("TXLINE_API_TOKEN", "test_api_token")
    monkeypatch.setenv("TXLINE_NETWORK", "devnet")
    monkeypatch.setenv("TXLINE_API_BASE_URL", "https://txline.test/api")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def sample_scores_frame_data() -> dict[str, Any]:
    """Return one realistic raw football scores message."""
    return {
        "fixtureId": 18237038,
        "gameState": 2,
        "startTime": 1784055600000,
        "isTeam": True,
        "fixtureGroupId": 9001,
        "competitionId": 72,
        "countryId": 0,
        "sportId": 1,
        "participant1IsHome": True,
        "participant1Id": 250,
        "participant2Id": 251,
        "action": "shot_on_target",
        "id": "1784056500000:12",
        "ts": 1784056500000,
        "connectionId": "connection-123",
        "seq": 12,
    }


@pytest.fixture
def sample_fixture_data() -> dict[str, Any]:
    """Return one realistic World Cup fixture snapshot record."""
    return {
        "FixtureId": 18237038,
        "Ts": 1784052000000,
        "StartTime": 1784055600000,
        "Competition": "World Cup",
        "CompetitionId": 72,
        "FixtureGroupId": 9001,
        "Participant1Id": 250,
        "Participant1": "France",
        "Participant2Id": 251,
        "Participant2": "Spain",
        "Participant1IsHome": True,
        "GameState": 1,
    }
