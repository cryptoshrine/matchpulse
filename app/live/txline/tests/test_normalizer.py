"""Golden tests for normalization of a trimmed real TxLINE session."""

import json
from pathlib import Path
from typing import Any, cast

import pytest

from app.live.notification_formatter import detect_notification_triggers
from app.live.notification_schemas import EventAmendmentNotification
from app.live.processor import StateUpdater
from app.live.schemas import LiveEventFrame, LiveMatchState
from app.live.txline.normalizer import TxLineNormalizer

FIXTURE = Path(__file__).parent / "fixtures" / "sample_session.jsonl"
PENALTY_REVISIONS_FIXTURE = (
    Path(__file__).parent / "fixtures" / "france_spain_penalty_revisions.jsonl"
)
REAL_FRANCE_SPAIN_RECORDING = (
    Path(__file__).parents[4]
    / "data"
    / "txline_recordings"
    / "18237038_updates_recovery.jsonl"
)


def _raw_frames() -> list[dict[str, Any]]:
    """Load typed raw frames from the committed provider excerpt."""
    frames: list[dict[str, Any]] = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        envelope = cast(dict[str, Any], json.loads(line))
        frames.append(cast(dict[str, Any], envelope["data"]))
    return frames


def _normalize_session() -> list[LiveEventFrame]:
    normalizer = TxLineNormalizer(match_id=18209181)
    events: list[LiveEventFrame] = []
    for raw in _raw_frames():
        events.extend(normalizer.to_phase_events(raw))
        event = normalizer.to_event_frame(raw)
        if event is not None:
            events.append(event)
    return events


def _normalize_recording(path: Path, match_id: int) -> list[LiveEventFrame]:
    """Normalize every envelope from one TxLINE JSONL recording."""
    normalizer = TxLineNormalizer(match_id=match_id)
    events: list[LiveEventFrame] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        envelope = cast(dict[str, Any], json.loads(line))
        raw = cast(dict[str, Any], envelope["data"])
        events.extend(normalizer.to_phase_events(raw))
        event = normalizer.to_event_frame(raw)
        if event is not None:
            events.append(event)
    return events


def test_golden_session_emits_phases_goals_and_card() -> None:
    """Real revisions collapse to two goals, one card, and four phases."""
    events = _normalize_session()

    assert [event.event_type for event in events].count("Shot") == 3
    assert [event.outcome for event in events].count("Goal") == 2
    assert [event.event_type for event in events].count("Card") == 1
    assert [event.event_type for event in events].count("Half Start") == 2
    assert [event.event_type for event in events].count("Half End") == 2

    first_goal = next(event for event in events if event.outcome == "Goal")
    assert first_goal.minute == 59
    assert first_goal.period == 2
    assert first_goal.team_name == "France"
    assert first_goal.player_name == "Mbappe Lottin, Kylian"
    assert first_goal.source == "txline"


def test_unconfirmed_and_incomplete_revisions_are_not_emitted() -> None:
    """Disallowed goals and anonymous confirmed goal revisions are skipped."""
    events = _normalize_session()

    assert all("goal:495" not in event.event_id for event in events)
    assert sum("goal:683" in event.event_id for event in events) == 1


def test_penalty_outcome_sets_story_builder_marker() -> None:
    """Penalty outcomes always carry the shared shot_type marker."""
    raw = {
        "FixtureId": 18209181,
        "Participant1Id": 1999,
        "Participant2Id": 2530,
        "StatusId": 2,
        "Action": "penalty_outcome",
        "Id": 302,
        "Participant": 1,
        "Confirmed": True,
        "Clock": {"Seconds": 1665},
        "Data": {"Outcome": "Missed"},
    }

    event = TxLineNormalizer(match_id=18209181).to_event_frame(raw)

    assert event is not None
    assert event.event_type == "Shot"
    assert event.outcome == "Saved"
    assert event.raw_data["shot_type"] == "Penalty"


def test_game_state_is_used_when_status_id_is_absent() -> None:
    """Documented integer GameState snapshots provide a phase fallback."""
    raw = {
        "FixtureId": 18209181,
        "GameState": 2,
        "Action": "status",
        "Clock": {"Seconds": 0},
    }

    events = TxLineNormalizer(match_id=18209181).to_phase_events(raw)

    assert len(events) == 1
    assert events[0].event_type == "Half Start"
    assert events[0].period == 1
    assert events[0].raw_data["txline_game_state_status"] == "live"


def test_penalty_award_and_outcome_are_intentionally_separate_events() -> None:
    """Award and resolution remain distinct notifications in chronology."""
    base: dict[str, Any] = {
        "FixtureId": 18209181,
        "Participant1Id": 1999,
        "Participant2Id": 2530,
        "StatusId": 2,
        "Participant": 1,
        "Confirmed": True,
        "Clock": {"Seconds": 1665},
    }
    award = {**base, "Action": "penalty", "Id": 296, "Data": {}}
    outcome = {
        **base,
        "Action": "penalty_outcome",
        "Id": 302,
        "Data": {"Outcome": "Missed"},
    }
    normalizer = TxLineNormalizer(match_id=18209181)

    award_event = normalizer.to_event_frame(award)
    outcome_event = normalizer.to_event_frame(outcome)

    assert award_event is not None
    assert outcome_event is not None
    assert award_event.event_id != outcome_event.event_id
    assert award_event.outcome is None
    assert outcome_event.outcome == "Saved"
    assert award_event.raw_data["shot_type"] == "Penalty"
    assert outcome_event.raw_data["shot_type"] == "Penalty"


async def test_penalty_revision_emits_non_scoring_scorer_amendment() -> None:
    """A richer same-Id revision amends narrative without a second goal."""
    events = _normalize_recording(PENALTY_REVISIONS_FIXTURE, match_id=18237038)
    penalty_events = [
        event
        for event in events
        if event.raw_data.get("amends_event_id")
        == "txline:18237038:penalty_outcome:213"
        or event.event_id == "txline:18237038:penalty_outcome:213"
    ]

    assert len(penalty_events) == 2
    canonical, amendment = penalty_events
    assert canonical.event_index == 221
    assert canonical.player_name is None
    assert amendment.event_type == "Event Amendment"
    assert amendment.event_index == 222
    assert amendment.player_name == "Oyarzabal Ugarte, Mikel"
    assert amendment.raw_data["txline_revision"] == "enrichment"

    updater = StateUpdater(
        LiveMatchState(
            match_id=18237038,
            home_team="France",
            away_team="Spain",
            home_team_id=1999,
            away_team_id=3021,
            source="txline",
        )
    )
    state_after_goal = await updater.process_event(canonical)
    state_after_amendment = await updater.process_event(amendment)
    notification = detect_notification_triggers(amendment, state_after_amendment)

    assert state_after_goal.away_score == 1
    assert state_after_amendment.away_score == 1
    assert isinstance(notification, EventAmendmentNotification)
    assert notification.player_name == "Oyarzabal Ugarte, Mikel"
    assert "SCORER CONFIRMED" in notification.message


@pytest.mark.skipif(
    not REAL_FRANCE_SPAIN_RECORDING.is_file(),
    reason="Full licensed recording is intentionally not committed",
)
def test_full_france_spain_recording_preserves_goal_attribution() -> None:
    """All 1,027 real envelopes yield the sequence-222 scorer amendment."""
    assert len(REAL_FRANCE_SPAIN_RECORDING.read_text(encoding="utf-8").splitlines()) == 1027

    events = _normalize_recording(REAL_FRANCE_SPAIN_RECORDING, match_id=18237038)
    amendments = [
        event
        for event in events
        if event.raw_data.get("amends_event_id")
        == "txline:18237038:penalty_outcome:213"
    ]

    assert len(amendments) == 1
    assert amendments[0].event_index == 222
    assert amendments[0].player_id == 463984
    assert amendments[0].player_name == "Oyarzabal Ugarte, Mikel"
