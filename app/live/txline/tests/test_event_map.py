"""Tests for evidence-backed TxLINE action and phase mappings."""

import pytest

from app.live.txline.event_map import (
    GAME_STATE_TO_STATUS,
    GAME_STATE_TO_STATUS_ID,
    STATUS_ID_TO_PHASE,
    TXLINE_ACTION_TO_HISTORICAL,
    normalize_action,
)


@pytest.mark.parametrize(("action", "expected"), TXLINE_ACTION_TO_HISTORICAL.items())
def test_every_action_mapping(action: str, expected: str) -> None:
    """Every declared action maps to its provider-neutral spelling."""
    assert normalize_action(action) == expected


def test_unknown_action_has_readable_fallback() -> None:
    """Unknown actions degrade to a readable title instead of raising."""
    assert normalize_action("brand_new-action") == "Brand New Action"


@pytest.mark.parametrize(("game_state", "status"), GAME_STATE_TO_STATUS.items())
def test_every_game_state_mapping(game_state: int, status: str) -> None:
    """The documented GameState table remains complete and stable."""
    assert GAME_STATE_TO_STATUS[game_state] == status


def test_every_game_state_has_a_phase_fallback_contract() -> None:
    """Status labels and phase fallbacks cover the same snapshot states."""
    assert GAME_STATE_TO_STATUS_ID.keys() == GAME_STATE_TO_STATUS.keys()


def test_observed_status_ids_cover_regular_and_extra_time() -> None:
    """Observed StatusId phases collapse into Ball-AI's period range."""
    assert STATUS_ID_TO_PHASE[2] == ("live", 1, "Half Start")
    assert STATUS_ID_TO_PHASE[4] == ("live", 2, "Half Start")
    assert STATUS_ID_TO_PHASE[7][1] == 3
    assert STATUS_ID_TO_PHASE[9][1] == 4
    assert STATUS_ID_TO_PHASE[100][0] == "fulltime"
