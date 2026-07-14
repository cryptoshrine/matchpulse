"""Tests for permissive TxLINE raw-payload schemas."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.live.txline.schemas import (
    TxLineFixture,
    TxLineOddsPayload,
    TxLineScoresMessage,
)


def test_scores_message_parses_full_payload(sample_scores_frame_data: dict[str, Any]) -> None:
    message = TxLineScoresMessage.model_validate(sample_scores_frame_data)

    assert message.fixtureId == 18237038
    assert message.seq == 12


def test_scores_message_allows_unknown_nested_fields(
    sample_scores_frame_data: dict[str, Any],
) -> None:
    sample_scores_frame_data["football"] = {"stats": {"1001": 1}}

    message = TxLineScoresMessage.model_validate(sample_scores_frame_data)

    assert message.model_extra == {"football": {"stats": {"1001": 1}}}


def test_scores_message_allows_empty_payload() -> None:
    message = TxLineScoresMessage.model_validate({})

    assert message.fixtureId is None


def test_fixture_parses_live_epoch_and_game_state(sample_fixture_data: dict[str, Any]) -> None:
    fixture = TxLineFixture.model_validate(sample_fixture_data)

    assert fixture.StartTime == 1784055600000
    assert fixture.GameState == 1


def test_fixture_requires_fixture_id() -> None:
    with pytest.raises(ValidationError):
        TxLineFixture.model_validate({})


def test_fixture_allows_unknown_fields(sample_fixture_data: dict[str, Any]) -> None:
    sample_fixture_data["Venue"] = {"Name": "Demo Stadium"}

    fixture = TxLineFixture.model_validate(sample_fixture_data)

    assert fixture.model_extra == {"Venue": {"Name": "Demo Stadium"}}


def test_odds_payload_allows_unknown_fields() -> None:
    payload = TxLineOddsPayload.model_validate(
        {"FixtureId": 18237038, "Prices": [1.5, 2.4], "FutureField": {"x": 1}}
    )

    assert payload.Prices == [1.5, 2.4]
    assert payload.model_extra == {"FutureField": {"x": 1}}
