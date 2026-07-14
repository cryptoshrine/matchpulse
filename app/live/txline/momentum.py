"""Lightweight rolling momentum signal for location-free TxLINE events."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Final
from uuid import uuid4

from app.core.logging import get_logger
from app.live.notification_formatter import RED_CARD_OUTCOMES
from app.live.notification_schemas import MomentumShiftNotification
from app.live.schemas import LiveEventFrame, LiveMatchState

logger = get_logger(__name__)

EVENT_WEIGHTS: Final[dict[tuple[str, str | None], float]] = {
    ("Shot", "Goal"): 3.0,
    ("Shot", "Saved"): 1.0,
    ("Shot", "Post"): 0.6,
    ("Shot", "Off T"): 0.4,
    ("Free Kick", "Danger"): 0.5,
    ("Free Kick", "HighDanger"): 0.5,
    ("Corner", None): 0.8,
}
RED_CARD_PENALTY: Final[float] = -2.0


@dataclass(frozen=True, slots=True)
class _MomentumEntry:
    """One weighted event retained in the rolling window."""

    minute: int
    team_id: int
    weight: float


def _empty_momentum_window() -> deque[_MomentumEntry]:
    """Return a typed empty momentum window."""
    return deque()


@dataclass(slots=True)
class MomentumTracker:
    """Track a normalized home-away momentum delta over a sliding window."""

    match_id: int
    window_minutes: int = 10
    alert_threshold: float = 0.45
    min_contributing_events: int = 3
    _window: deque[_MomentumEntry] = field(default_factory=_empty_momentum_window, init=False)
    _previous_delta: float | None = field(default=None, init=False)
    _current_delta: float = field(default=0.0, init=False)

    @property
    def current_delta(self) -> float:
        """Return the latest normalized home-minus-away momentum delta."""
        return self._current_delta

    async def add_event(
        self,
        event: LiveEventFrame,
        state: LiveMatchState,
    ) -> MomentumShiftNotification | None:
        """Add an event and emit an alert on a threshold-crossing sign flip.

        Args:
            event: Latest normalized event.
            state: Current provider-neutral match state.

        Returns:
            Momentum alert when the documented trigger fires, otherwise None.
        """
        cutoff = event.minute - self.window_minutes
        while self._window and self._window[0].minute < cutoff:
            self._window.popleft()

        weight = EVENT_WEIGHTS.get((event.event_type, event.outcome), 0.0)
        if event.event_type == "Card" and event.outcome in RED_CARD_OUTCOMES:
            weight = RED_CARD_PENALTY
        if weight != 0.0 and event.team_id is not None:
            self._window.append(
                _MomentumEntry(minute=event.minute, team_id=event.team_id, weight=weight)
            )

        home_sum = sum(
            entry.weight for entry in self._window if entry.team_id == state.home_team_id
        )
        away_sum = sum(
            entry.weight for entry in self._window if entry.team_id == state.away_team_id
        )
        denominator = abs(home_sum) + abs(away_sum)
        normalized_delta = (home_sum - away_sum) / denominator if denominator > 0 else 0.0
        normalized_delta = max(-1.0, min(1.0, normalized_delta))
        contributing_events = len(self._window)

        previous_delta = self._previous_delta
        self._previous_delta = normalized_delta
        self._current_delta = normalized_delta
        logger.debug(
            "live.txline.momentum.window_updated",
            match_id=self.match_id,
            minute=event.minute,
            momentum_delta=normalized_delta,
            contributing_events=contributing_events,
        )

        sign_flipped = (
            previous_delta is not None
            and previous_delta != 0.0
            and normalized_delta != 0.0
            and (normalized_delta > 0) != (previous_delta > 0)
        )
        if not (
            abs(normalized_delta) >= self.alert_threshold
            and contributing_events >= self.min_contributing_events
            and sign_flipped
        ):
            return None

        team_name = state.home_team if normalized_delta > 0 else state.away_team
        notification = MomentumShiftNotification(
            notification_id=f"notif_{uuid4().hex[:12]}",
            match_id=self.match_id,
            event_id=event.event_id,
            message=f"MOMENTUM SHIFT: {team_name} are taking control ({event.minute}')",
            team_name=team_name,
            minute=event.minute,
            momentum_delta=normalized_delta,
            contributing_events=contributing_events,
        )
        logger.info(
            "live.txline.momentum.shift_detected",
            match_id=self.match_id,
            team_name=team_name,
            minute=event.minute,
            momentum_delta=normalized_delta,
        )
        return notification
