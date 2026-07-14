"""TxLINE football action and match-phase mappings.

Evidence: the tables below were derived on 2026-07-14 by parsing complete
TxLINE historical sessions plus the 1,027-frame France-Spain updates recovery.
Frames use PascalCase top-level fields, nested ``Data``/``Stats`` objects, and
the string ``GameState='scheduled'`` throughout. The useful phase signal is
``StatusId``: 2/3/4/5 represent first half/halftime/second half/fulltime, while
6-10 cover extra time. Stats keys are stat-major, not participant-major: base
keys 1/2 are participant 1/2 goals, 3/4 yellows, 5/6 reds, and 7/8 corners;
period prefixes 1000/2000/3000/etc. are added to those base keys. Confirmed
actions include goal, shot, free_kick, corner, penalty, penalty_outcome,
yellow_card, substitution, var, and var_end. Red-card and shootout mappings
remain proposed because the inspected matches did not contain those actions.
"""

from typing import Final

TXLINE_ACTION_TO_HISTORICAL: Final[dict[str, str]] = {
    # Confirmed in both inspected sessions.
    "goal": "Shot",
    "shot": "Shot",
    "yellow_card": "Card",
    "substitution": "Substitution",
    "free_kick": "Free Kick",
    "corner": "Corner",
    "var": "VAR Review",
    "var_end": "VAR Review",
    "penalty": "Shot",
    "penalty_outcome": "Shot",
    "halftime_finalised": "Half End",
    "game_finalised": "Half End",
    "injury": "Injury Stoppage",
    # Proposed, unobserved variants supported defensively.
    "red_card": "Card",
    "second_yellow_card": "Card",
    "penalty_result": "Shot",
}

SHOT_OUTCOMES: Final[dict[str, str | None]] = {
    "OnTarget": "Saved",
    "OffTarget": "Off T",
    "Woodwork": "Post",
    "Blocked": "Blocked",
    "Goal": "Goal",
}

PENALTY_OUTCOMES: Final[dict[str, str | None]] = {
    "Scored": "Goal",
    "Missed": "Saved",
    "Retake": None,
}

CARD_OUTCOMES: Final[dict[str, str]] = {
    "yellow_card": "Yellow Card",
    "red_card": "Red Card",
    "second_yellow_card": "Second Yellow",
}

# Fixture-snapshot values from TxLINE's documented integer GameState contract.
# Historical score frames did not expose these values; they stayed "scheduled".
GAME_STATE_TO_STATUS: Final[dict[int, str]] = {
    1: "pending",
    2: "live",
    3: "halftime",
    4: "live",
    5: "fulltime",
    7: "extra_time",
    9: "extra_time",
    12: "extra_time",
    14: "unchanged",
    15: "fulltime",
    19: "pending",
}

# Documented GameState snapshots mapped onto the observed StatusId phase
# contract. ``None`` means the snapshot changes no phase boundary.
GAME_STATE_TO_STATUS_ID: Final[dict[int, int | None]] = {
    1: 1,
    2: 2,
    3: 3,
    4: 4,
    5: 5,
    7: 7,
    9: 9,
    12: None,
    14: None,
    15: 5,
    19: 1,
}

# Observed score-frame StatusId → (state status, Ball-AI period, transition).
STATUS_ID_TO_PHASE: Final[dict[int, tuple[str, int, str | None]]] = {
    1: ("pending", 1, None),
    2: ("live", 1, "Half Start"),
    3: ("halftime", 1, "Half End"),
    4: ("live", 2, "Half Start"),
    5: ("fulltime", 2, "Half End"),
    6: ("extra_time", 2, "Half End"),
    7: ("extra_time", 3, "Half Start"),
    8: ("extra_time", 3, "Half End"),
    9: ("extra_time", 4, "Half Start"),
    10: ("fulltime", 4, "Half End"),
    100: ("fulltime", 2, None),
}

# Confirmed by reconciling the final Score and Stats objects in both sessions.
PERIOD_STAT_PREFIXES: Final[dict[int, str]] = {
    0: "total",
    1000: "h1",
    2000: "ht",
    3000: "h2",
    4000: "et1",
    5000: "et2",
    6000: "pe",
    7000: "et_total",
}

BASE_STAT_KEYS: Final[dict[int, str]] = {
    1: "participant1_goals",
    2: "participant2_goals",
    3: "participant1_yellow_cards",
    4: "participant2_yellow_cards",
    5: "participant1_red_cards",
    6: "participant2_red_cards",
    7: "participant1_corners",
    8: "participant2_corners",
}


def normalize_action(action: str) -> str:
    """Convert a TxLINE action name to Ball-AI's historical convention.

    Args:
        action: Raw snake-case TxLINE action.

    Returns:
        Explicit mapped name or a readable title-cased fallback.

    Examples:
        >>> normalize_action("free_kick")
        'Free Kick'
        >>> normalize_action("goal")
        'Shot'
        >>> normalize_action("brand_new_action")
        'Brand New Action'
    """
    normalized = action.lower().strip()
    if normalized in TXLINE_ACTION_TO_HISTORICAL:
        return TXLINE_ACTION_TO_HISTORICAL[normalized]
    return normalized.replace("_", " ").replace("-", " ").title()
