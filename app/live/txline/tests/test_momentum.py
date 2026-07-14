"""Tests for the location-free TxLINE momentum signal."""

from app.live.schemas import LiveEventFrame, LiveMatchState
from app.live.txline.momentum import MomentumTracker


def _state() -> LiveMatchState:
    return LiveMatchState(
        match_id=44,
        home_team="France",
        away_team="Morocco",
        home_team_id=1,
        away_team_id=2,
        source="txline",
    )


def _event(
    event_id: str,
    team_id: int,
    event_type: str,
    outcome: str | None,
    minute: int,
) -> LiveEventFrame:
    return LiveEventFrame(
        event_id=event_id,
        match_id=44,
        event_type=event_type,
        minute=minute,
        second=0,
        period=1,
        team_id=team_id,
        team_name="France" if team_id == 1 else "Morocco",
        player_id=None,
        player_name=None,
        location=None,
        outcome=outcome,
        xg=None,
        freeze_frame=None,
        recipient_id=None,
        event_index=None,
        source="txline",
    )


async def test_below_threshold_does_not_trigger() -> None:
    tracker = MomentumTracker(match_id=44)

    notification = await tracker.add_event(_event("1", 1, "Shot", "Off T", 2), _state())

    assert notification is None
    assert tracker.current_delta == 1.0


async def test_sign_flip_triggers_once_then_sustained_pressure_does_not() -> None:
    tracker = MomentumTracker(match_id=44)
    state = _state()
    sequence = [
        _event("1", 1, "Shot", "Off T", 1),
        _event("2", 2, "Shot", "Off T", 2),
        _event("3", 2, "Shot", "Off T", 3),
    ]
    for event in sequence:
        assert await tracker.add_event(event, state) is None

    notification = await tracker.add_event(_event("4", 1, "Shot", "Goal", 4), state)
    sustained = await tracker.add_event(_event("5", 1, "Shot", "Saved", 5), state)

    assert notification is not None
    assert notification.notification_type == "momentum_shift"
    assert notification.team_name == "France"
    assert notification.momentum_delta > 0.45
    assert notification.contributing_events == 4
    assert sustained is None


async def test_window_evicts_old_events() -> None:
    tracker = MomentumTracker(match_id=44, window_minutes=10)
    state = _state()
    await tracker.add_event(_event("1", 1, "Corner", None, 1), state)

    await tracker.add_event(_event("2", 2, "Substitution", None, 12), state)

    assert tracker.current_delta == 0.0


async def test_red_card_penalizes_offending_team() -> None:
    tracker = MomentumTracker(match_id=44)

    await tracker.add_event(_event("1", 1, "Card", "Red Card", 6), _state())

    assert tracker.current_delta == -1.0
