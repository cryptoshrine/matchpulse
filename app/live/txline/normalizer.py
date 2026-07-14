"""Normalize observed TxLINE score frames into Ball-AI live events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeGuard, cast

from app.core.logging import get_logger
from app.live.schemas import LiveEventFrame
from app.live.txline.event_map import (
    CARD_OUTCOMES,
    GAME_STATE_TO_STATUS,
    GAME_STATE_TO_STATUS_ID,
    PENALTY_OUTCOMES,
    SHOT_OUTCOMES,
    STATUS_ID_TO_PHASE,
    normalize_action,
)

logger = get_logger(__name__)

IGNORED_ACTIONS = {
    "coverage_update",
    "comment",
    "connected",
    "disconnected",
    "lineups",
    "venue",
    "weather",
    "pitch",
    "jersey",
    "players_warming_up",
    "players_on_the_pitch",
    "kickoff_team",
    "standby",
    "status",
    "kickoff",
    "clock_adjustment",
    "possession",
    "attack_possession",
    "safe_possession",
    "danger_possession",
    "high_danger_possession",
    "throw_in",
    "goal_kick",
    "possible",
    "action_amend",
    "action_discarded",
    "additional_time",
    "halftime_finalised",
    "game_finalised",
}


def _raw_value(raw: dict[str, Any], *names: str) -> Any:
    """Return the first present spelling of a provider field."""
    for name in names:
        if name in raw:
            return raw[name]
    return None


def _as_int(value: Any) -> int | None:
    """Coerce an integer-like provider value without accepting booleans."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _as_dict(value: Any) -> dict[str, Any]:
    """Return a provider object as a typed dictionary or an empty mapping."""
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in cast(dict[object, Any], value).items()}


def _is_any_list(value: object) -> TypeGuard[list[Any]]:
    """Narrow untyped provider arrays to a strict ``list[Any]``."""
    return isinstance(value, list)


@dataclass(frozen=True, slots=True)
class _RevisionSnapshot:
    """Meaningful attribution fields retained for one provider event ID."""

    player_id: int | None
    player_name: str | None
    team_id: int | None
    team_name: str | None
    outcome: str | None
    sequence: int | None

    def enriches(self, previous: _RevisionSnapshot) -> bool:
        """Return whether this revision adds or corrects narrative attribution."""
        return any(
            (
                self.player_id is not None and self.player_id != previous.player_id,
                self.player_name is not None and self.player_name != previous.player_name,
                self.team_id is not None and self.team_id != previous.team_id,
                self.team_name is not None and self.team_name != previous.team_name,
                self.outcome is not None and self.outcome != previous.outcome,
            )
        )


class TxLineNormalizer:
    """Convert raw TxLINE football updates into ``LiveEventFrame`` objects.

    One instance must live for a complete subscription or replay. It keeps the
    phase-transition, confirmed-action, lineup, and clock context required to
    collapse TxLINE's repeated revisions into one stable Ball-AI event.
    """

    def __init__(
        self,
        match_id: int | None = None,
        kickoff: datetime | None = None,
    ) -> None:
        """Initialize subscription-scoped normalization state.

        Args:
            match_id: Optional fixture identifier fixed for this instance.
            kickoff: Optional fallback kickoff time. Observed football frames
                carry a more reliable match ``Clock.Seconds`` value.
        """
        self._match_id = match_id
        self._kickoff = kickoff
        self._current_period: dict[int, int] = {}
        self._last_clock_seconds: dict[int, int] = {}
        self._emitted_phase_events: set[tuple[int, str, int]] = set()
        self._event_revisions: dict[tuple[int, str, str], _RevisionSnapshot] = {}
        self._team_names: dict[int, str] = {}
        self._player_names: dict[int, str] = {}

    def to_phase_events(
        self,
        raw: dict[str, Any],
        match_id: int | None = None,
    ) -> list[LiveEventFrame]:
        """Synthesize phase events from ``StatusId`` or integer ``GameState``.

        Args:
            raw: One raw TxLINE score frame.
            match_id: Optional fixture override.

        Returns:
            Zero or one deduplicated phase-transition events.
        """
        resolved_match_id = self._resolve_match_id(raw, match_id)
        self._ingest_context(raw, resolved_match_id)
        action = str(_raw_value(raw, "Action", "action") or "").lower()
        status_id = _as_int(_raw_value(raw, "StatusId", "statusId"))
        game_state = _as_int(_raw_value(raw, "GameState", "gameState"))
        fallback_status: str | None = None

        if action == "halftime_finalised":
            status_id = 3
        elif action == "game_finalised":
            status_id = 100
        elif status_id is None and game_state is not None:
            if game_state not in GAME_STATE_TO_STATUS_ID:
                logger.warning(
                    "live.txline.event_map.unknown_game_state",
                    match_id=resolved_match_id,
                    game_state=game_state,
                )
                return []
            status_id = GAME_STATE_TO_STATUS_ID[game_state]
            fallback_status = GAME_STATE_TO_STATUS[game_state]
            if game_state == 15:
                logger.warning(
                    "live.txline.event_map.abandoned_match",
                    match_id=resolved_match_id,
                    game_state=game_state,
                )

        if status_id is None:
            return []

        phase = STATUS_ID_TO_PHASE.get(status_id)
        if phase is None:
            logger.warning(
                "live.txline.event_map.unknown_status_id",
                match_id=resolved_match_id,
                status_id=status_id,
            )
            return []

        _status, mapped_period, transition = phase
        current_period = self._current_period.get(resolved_match_id, mapped_period)
        if status_id == 100:
            mapped_period = current_period
            transition = "Half End"
        else:
            self._current_period[resolved_match_id] = mapped_period

        if transition is None:
            return []

        phase_key = (resolved_match_id, transition, mapped_period)
        if phase_key in self._emitted_phase_events:
            return []
        self._emitted_phase_events.add(phase_key)

        minute, second = self._match_clock(raw, resolved_match_id, status_id=status_id)
        event = LiveEventFrame(
            event_id=(
                f"txline:{resolved_match_id}:phase:"
                f"{transition.lower().replace(' ', '-')}:p{mapped_period}"
            ),
            match_id=resolved_match_id,
            event_type=transition,
            minute=minute,
            second=second,
            period=mapped_period,
            team_id=None,
            team_name=None,
            player_id=None,
            player_name=None,
            location=None,
            outcome=None,
            xg=None,
            freeze_frame=None,
            recipient_id=None,
            event_index=None,
            raw_data={
                **raw,
                "txline_status_id": status_id,
                **(
                    {"txline_game_state_status": fallback_status}
                    if fallback_status is not None
                    else {}
                ),
            },
            source="txline",
        )
        logger.info(
            "live.txline.normalizer.phase_emitted",
            match_id=resolved_match_id,
            event_type=transition,
            period=mapped_period,
            status_id=status_id,
        )
        return [event]

    def to_event_frame(
        self,
        raw: dict[str, Any],
        match_id: int | None = None,
    ) -> LiveEventFrame | None:
        """Normalize one confirmed football action.

        Args:
            raw: One raw TxLINE score frame.
            match_id: Optional fixture override.

        Returns:
            A provider-neutral event, or ``None`` for metadata, unconfirmed
            revisions, and already-emitted revisions.
        """
        resolved_match_id = self._resolve_match_id(raw, match_id)
        self._ingest_context(raw, resolved_match_id)
        action = str(_raw_value(raw, "Action", "action") or "").lower().strip()
        if not action or action in IGNORED_ACTIONS:
            logger.debug(
                "live.txline.normalizer.event_skipped",
                match_id=resolved_match_id,
                reason="metadata_or_missing_action",
                action=action or None,
            )
            return None

        confirmed = _raw_value(raw, "Confirmed", "confirmed")
        if confirmed is False:
            return None

        data = _as_dict(_raw_value(raw, "Data", "data"))
        player_id = _as_int(_raw_value(data, "PlayerId", "playerId"))
        if player_id is None and action == "substitution":
            player_id = _as_int(_raw_value(data, "PlayerInId", "playerInId"))

        # Goals/cards arrive as repeated confirmed revisions; the final revision
        # carries PlayerId. Waiting for it prevents duplicate/anonymous alerts.
        if action in {"goal", "yellow_card", "red_card", "second_yellow_card"}:
            if confirmed is True and player_id is None:
                return None

        raw_event_id = _raw_value(raw, "Id", "id")
        raw_sequence = _as_int(_raw_value(raw, "Seq", "seq"))
        stable_id = str(raw_event_id if raw_event_id is not None else raw_sequence)
        event_key = (resolved_match_id, action, stable_id)

        participant = _as_int(_raw_value(raw, "Participant", "participant"))
        if participant is None:
            participant = _as_int(_raw_value(data, "Participant", "participant"))
        team_id = self._team_id(raw, participant)
        outcome = self._outcome(action, data)
        event_type = normalize_action(action)
        minute, second = self._match_clock(raw, resolved_match_id)
        period = self._current_period.get(resolved_match_id, 1)
        team_name = self._team_names.get(team_id) if team_id is not None else None
        player_name = self._player_names.get(player_id) if player_id is not None else None
        revision = _RevisionSnapshot(
            player_id=player_id,
            player_name=player_name,
            team_id=team_id,
            team_name=team_name,
            outcome=outcome,
            sequence=raw_sequence,
        )
        previous_revision = self._event_revisions.get(event_key)
        canonical_event_id = f"txline:{resolved_match_id}:{action}:{stable_id}"
        if previous_revision is not None:
            if not revision.enriches(previous_revision):
                return None
            if raw_sequence is None:
                logger.warning(
                    "live.txline.normalizer.revision_skipped",
                    match_id=resolved_match_id,
                    action=action,
                    provider_event_id=stable_id,
                    reason="missing_sequence",
                )
                return None
            self._event_revisions[event_key] = revision
            return self._build_amendment_event(
                raw=raw,
                canonical_event_id=canonical_event_id,
                sequence=raw_sequence,
                event_type=event_type,
                action=action,
                minute=minute,
                second=second,
                period=period,
                team_id=team_id,
                team_name=team_name,
                player_id=player_id,
                player_name=player_name,
                outcome=outcome,
                match_id=resolved_match_id,
            )

        self._event_revisions[event_key] = revision

        raw_data = dict(raw)
        # The award and its later resolution intentionally remain separate:
        # clients notify once for the decision and again for the outcome.
        if action in {"penalty", "penalty_outcome", "penalty_result"}:
            raw_data["shot_type"] = "Penalty"
        if action in {"var", "var_end"}:
            raw_data["var_type"] = _raw_value(data, "Type", "type")
            raw_data["var_outcome"] = _raw_value(data, "Outcome", "outcome")

        event = LiveEventFrame(
            event_id=canonical_event_id,
            match_id=resolved_match_id,
            event_type=event_type,
            minute=minute,
            second=second,
            period=period,
            team_id=team_id,
            team_name=team_name,
            player_id=player_id,
            player_name=player_name,
            location=None,
            outcome=outcome,
            xg=None,
            freeze_frame=None,
            recipient_id=None,
            event_index=raw_sequence,
            raw_data=raw_data,
            source="txline",
        )
        logger.debug(
            "live.txline.normalizer.event_normalized",
            match_id=resolved_match_id,
            event_type=event.event_type,
            event_id=event.event_id,
            minute=event.minute,
        )
        return event

    def _build_amendment_event(
        self,
        *,
        raw: dict[str, Any],
        canonical_event_id: str,
        sequence: int,
        event_type: str,
        action: str,
        minute: int,
        second: int,
        period: int,
        team_id: int | None,
        team_name: str | None,
        player_id: int | None,
        player_name: str | None,
        outcome: str | None,
        match_id: int,
    ) -> LiveEventFrame:
        """Build a non-scoring event for meaningful same-ID enrichment."""
        raw_data = dict(raw)
        raw_data.update(
            {
                "txline_revision": "enrichment",
                "amends_event_id": canonical_event_id,
                "amended_action": action,
                "amended_event_type": event_type,
                "amended_outcome": outcome,
                "txline_provider_sequence": sequence,
            }
        )
        if action in {"penalty", "penalty_outcome", "penalty_result"}:
            raw_data["shot_type"] = "Penalty"

        event = LiveEventFrame(
            event_id=f"{canonical_event_id}:amendment:{sequence}",
            match_id=match_id,
            event_type="Event Amendment",
            minute=minute,
            second=second,
            period=period,
            team_id=team_id,
            team_name=team_name,
            player_id=player_id,
            player_name=player_name,
            location=None,
            outcome=None,
            xg=None,
            freeze_frame=None,
            recipient_id=None,
            event_index=sequence,
            raw_data=raw_data,
            source="txline",
        )
        logger.info(
            "live.txline.normalizer.revision_enriched",
            match_id=match_id,
            event_id=event.event_id,
            amends_event_id=canonical_event_id,
            player_id=player_id,
            sequence=sequence,
        )
        return event

    def _resolve_match_id(self, raw: dict[str, Any], match_id: int | None) -> int:
        """Resolve the configured, explicit, or wire fixture identifier."""
        resolved = match_id or self._match_id
        if resolved is None:
            resolved = _as_int(_raw_value(raw, "FixtureId", "fixtureId"))
        if resolved is None:
            raise ValueError("TxLINE frame is missing FixtureId and no match_id was configured")
        return resolved

    def _ingest_context(self, raw: dict[str, Any], match_id: int) -> None:
        """Update lineup names and clock/period context from a raw frame."""
        clock = _as_dict(_raw_value(raw, "Clock", "clock"))
        clock_seconds = _as_int(_raw_value(clock, "Seconds", "seconds"))
        if clock_seconds is not None:
            self._last_clock_seconds[match_id] = max(0, clock_seconds)

        status_id = _as_int(_raw_value(raw, "StatusId", "statusId"))
        if status_id in STATUS_ID_TO_PHASE and status_id != 100:
            self._current_period[match_id] = STATUS_ID_TO_PHASE[status_id][1]

        lineups = _raw_value(raw, "Lineups", "lineups")
        if not _is_any_list(lineups):
            return
        for team_value in lineups:
            team = _as_dict(team_value)
            team_id = _as_int(_raw_value(team, "normativeId", "NormativeId"))
            team_name = _raw_value(team, "preferredName", "PreferredName")
            if team_id is not None and isinstance(team_name, str):
                self._team_names[team_id] = team_name
            players = _raw_value(team, "lineups", "Lineups")
            if not _is_any_list(players):
                continue
            for lineup_value in players:
                lineup = _as_dict(lineup_value)
                player = _as_dict(_raw_value(lineup, "player", "Player"))
                player_id = _as_int(_raw_value(player, "normativeId", "NormativeId"))
                player_name = _raw_value(player, "preferredName", "PreferredName")
                if player_id is not None and isinstance(player_name, str):
                    self._player_names[player_id] = player_name

    def _team_id(self, raw: dict[str, Any], participant: int | None) -> int | None:
        """Resolve participant ordinal 1/2 to its provider team identifier."""
        if participant == 1:
            return _as_int(_raw_value(raw, "Participant1Id", "participant1Id"))
        if participant == 2:
            return _as_int(_raw_value(raw, "Participant2Id", "participant2Id"))
        return None

    def _match_clock(
        self,
        raw: dict[str, Any],
        match_id: int,
        *,
        status_id: int | None = None,
    ) -> tuple[int, int]:
        """Resolve minute/second from the observed provider match clock."""
        clock = _as_dict(_raw_value(raw, "Clock", "clock"))
        elapsed_seconds = _as_int(_raw_value(clock, "Seconds", "seconds"))
        if elapsed_seconds is None:
            elapsed_seconds = self._last_clock_seconds.get(match_id)
        if elapsed_seconds is None and status_id is not None:
            elapsed_seconds = {
                3: 45 * 60,
                4: 45 * 60,
                5: 90 * 60,
                6: 90 * 60,
                7: 90 * 60,
                8: 105 * 60,
                9: 105 * 60,
                10: 120 * 60,
                100: 90 * 60,
            }.get(status_id, 0)
        if elapsed_seconds is None:
            elapsed_seconds = 0
        elapsed_seconds = min(max(elapsed_seconds, 0), 120 * 60)
        self._last_clock_seconds[match_id] = elapsed_seconds
        return divmod(elapsed_seconds, 60)

    @staticmethod
    def _outcome(action: str, data: dict[str, Any]) -> str | None:
        """Map observed action-specific details to Ball-AI outcomes."""
        if action == "goal":
            return "Goal"
        if action == "shot":
            raw_outcome = _raw_value(data, "Outcome", "outcome")
            return SHOT_OUTCOMES.get(str(raw_outcome)) if raw_outcome is not None else None
        if action in CARD_OUTCOMES:
            return CARD_OUTCOMES[action]
        if action == "free_kick":
            free_kick_type = _raw_value(data, "FreeKickType", "freeKickType")
            return str(free_kick_type) if free_kick_type is not None else None
        if action in {"penalty_outcome", "penalty_result"}:
            raw_outcome = _raw_value(data, "Outcome", "outcome")
            return PENALTY_OUTCOMES.get(str(raw_outcome)) if raw_outcome is not None else None
        if action == "var_end":
            raw_outcome = _raw_value(data, "Outcome", "outcome")
            return str(raw_outcome) if raw_outcome is not None else None
        return None
