"""Business logic for MatchPulse card creation and proof capture."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.infographic.generate_ai_infographic_tool import create_infographic_generator
from app.live.schemas import LiveEventFrame, LiveMatchState
from app.live.txline.client import TxLineClient
from app.moments.models import MatchMoment
from app.moments.schemas import MomentMintUpdate
from app.visualizations.schemas import VizFormat, VizPlatform

logger = get_logger(__name__)

_PERIOD_STAT_PREFIX: dict[int, int] = {1: 1000, 2: 3000, 3: 4000, 4: 5000, 5: 6000}


def describe_event(event: LiveEventFrame) -> str:
    """Build a concise card and metadata description for one event."""
    player = event.player_name or "A player"
    team = event.team_name or "their team"
    effective_outcome = event.outcome or event.raw_data.get("amended_outcome")
    if event.raw_data.get("shot_type") == "Penalty" and effective_outcome == "Goal":
        return f"{player} converts a penalty for {team} in the {event.minute}' minute"
    if (
        event.event_type == "Shot"
        or event.raw_data.get("amended_event_type") == "Shot"
    ) and effective_outcome == "Goal":
        return f"{player} scores for {team} in the {event.minute}' minute"
    if event.event_type == "Card":
        return f"{player} receives a {event.outcome or 'card'} for {team} in the {event.minute}' minute"
    return f"{team}: {event.event_type} in the {event.minute}' minute"


def stat_keys_for_event(event: LiveEventFrame) -> list[str]:
    """Choose stat-major proof keys from the real event participant and period.

    TxLINE uses base keys 1/2 for goals, 3/4 for yellows, 5/6 for reds,
    and 7/8 for corners. Period-specific keys add 1000 for first half,
    3000 for second half, 4000/5000 for extra time, or 6000 for penalties.
    """
    participant = event.raw_data.get("Participant") or event.raw_data.get("participant")
    participant_number = participant if participant in {1, 2} else None
    effective_event_type = str(event.raw_data.get("amended_event_type") or event.event_type)
    effective_outcome = event.outcome or event.raw_data.get("amended_outcome")
    base_key: int | None = None
    if participant_number is not None:
        if effective_event_type == "Shot" and effective_outcome == "Goal":
            base_key = participant_number
        elif effective_event_type == "Card" and effective_outcome == "Yellow Card":
            base_key = participant_number + 2
        elif effective_event_type == "Card" and effective_outcome in {
            "Red Card",
            "Second Yellow",
        }:
            base_key = participant_number + 4
        elif effective_event_type == "Corner":
            base_key = participant_number + 6

    if base_key is None:
        return ["1", "2"]
    keys = [str(base_key)]
    period_prefix = _PERIOD_STAT_PREFIX.get(event.period)
    if period_prefix is not None:
        keys.append(str(period_prefix + base_key))
    return keys


async def _render_card(
    event: LiveEventFrame,
    state: LiveMatchState,
    description: str,
) -> str | None:
    """Render a best-effort AI card from provider-neutral live data."""
    settings = get_settings()
    if not settings.ai_infographic_enabled:
        logger.info("moments.card_render_skipped", reason="feature_disabled")
        return None
    generator = create_infographic_generator(output_dir="output")
    if generator is None:
        logger.info("moments.card_render_skipped", reason="client_unconfigured")
        return None
    result = await generator.generate(
        template="fan_engagement",
        data={
            "title": f"MatchPulse • {event.minute}'",
            "content_type": "stat_highlight",
            "highlight_stat": description,
            "comparison_data": {
                "home_team": state.home_team,
                "away_team": state.away_team,
                "home_score": state.home_score,
                "away_score": state.away_score,
                "minute": event.minute,
            },
        },
        chart_images=None,
        platform=VizPlatform.TWITTER,
        output_format=VizFormat.PNG,
        data_attribution="TxODDS TxLINE",
        # Cards get minted; keep them small enough for NFT image-preview proxies
        # (e.g. Solana Explorer) to render — the raw Gemini PNG is ~4MB/2.7K px.
        max_dimension=1200,
    )
    file_path = result.get("file_path")
    return str(file_path) if file_path else None


async def _fetch_txline_proof(
    fixture_id: int,
    seq: int,
    stat_keys: list[str],
) -> dict[str, Any]:
    """Fetch one authenticated multiproof through the shared TxLINE client."""
    return await TxLineClient().get_stat_validation(fixture_id, seq, stat_keys)


async def _find_existing_moment(
    db: AsyncSession,
    match_id: int,
    event_id: str,
) -> MatchMoment | None:
    """Return the persisted moment for this fixture/event, if one exists.

    Moments are unique on ``(match_id, event_id)``. The same event recurs on
    every replay, so callers use this to stay idempotent instead of inserting
    a duplicate.
    """
    result = await db.execute(
        select(MatchMoment).where(
            MatchMoment.match_id == match_id,
            MatchMoment.event_id == event_id,
        )
    )
    return result.scalar_one_or_none()


async def create_moment(
    db: AsyncSession,
    match_id: int,
    event: LiveEventFrame,
    state: LiveMatchState,
) -> MatchMoment:
    """Persist a moment with best-effort card rendering and TxLINE proof.

    Args:
        db: Async database session.
        match_id: TxLINE fixture identifier.
        event: Buffered provider-neutral source event.
        state: Current match state used for score context.

    Returns:
        Persisted moment record.
    """
    logger.info(
        "moments.create_started",
        match_id=match_id,
        event_id=event.event_id,
        event_type=event.event_type,
    )

    # Moments are unique on (match_id, event_id) and the same event recurs on
    # every replay. Return the existing moment instead of re-inserting (which
    # would violate the unique constraint) or re-rendering the card.
    existing = await _find_existing_moment(db, match_id, event.event_id)
    if existing is not None:
        logger.info(
            "moments.create_idempotent_hit",
            moment_id=existing.id,
            match_id=match_id,
            event_id=event.event_id,
        )
        return existing

    description = describe_event(event)
    card_image_url: str | None = None
    try:
        card_image_url = await _render_card(event, state, description)
    except Exception as exc:
        logger.warning(
            "moments.card_render_failed",
            match_id=match_id,
            event_id=event.event_id,
            error=str(exc),
            error_type=type(exc).__name__,
            exc_info=True,
        )

    txline_seq: int | None = None
    txline_proof_json: str | None = None
    if event.source == "txline" and event.event_index is not None and event.event_index >= 1:
        try:
            proof = await _fetch_txline_proof(
                fixture_id=match_id,
                seq=event.event_index,
                stat_keys=stat_keys_for_event(event),
            )
            txline_seq = event.event_index
            txline_proof_json = json.dumps(proof, separators=(",", ":"), sort_keys=True)
        except Exception as exc:
            logger.warning(
                "moments.proof_fetch_failed",
                match_id=match_id,
                event_id=event.event_id,
                seq=event.event_index,
                error=str(exc),
                error_type=type(exc).__name__,
                exc_info=True,
            )
    else:
        logger.warning(
            "moments.proof_fetch_skipped",
            match_id=match_id,
            event_id=event.event_id,
            reason="missing_real_txline_sequence",
        )

    moment = MatchMoment(
        match_id=match_id,
        event_id=event.event_id,
        event_type=event.event_type,
        minute=event.minute,
        description=description,
        card_image_url=card_image_url,
        txline_seq=txline_seq,
        txline_proof_json=txline_proof_json,
    )
    db.add(moment)
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent request created the same (match_id, event_id) between our
        # pre-check and commit. Roll back and return the winner's row.
        await db.rollback()
        existing = await _find_existing_moment(db, match_id, event.event_id)
        if existing is not None:
            logger.info(
                "moments.create_idempotent_race",
                moment_id=existing.id,
                match_id=match_id,
                event_id=event.event_id,
            )
            return existing
        raise
    await db.refresh(moment)
    logger.info(
        "moments.create_completed",
        moment_id=moment.id,
        match_id=match_id,
        event_id=event.event_id,
        has_card=card_image_url is not None,
        has_proof=txline_proof_json is not None,
    )
    return moment


async def get_moment(db: AsyncSession, moment_id: str) -> MatchMoment | None:
    """Load one moment by UUID."""
    return await db.get(MatchMoment, moment_id)


async def list_moments(
    db: AsyncSession,
    *,
    match_id: int | None,
    limit: int,
) -> list[MatchMoment]:
    """List newest moments with an optional match filter."""
    statement = select(MatchMoment).order_by(MatchMoment.created_at.desc()).limit(limit)
    if match_id is not None:
        statement = statement.where(MatchMoment.match_id == match_id)
    result = await db.execute(statement)
    return list(result.scalars().all())


async def update_mint(
    db: AsyncSession,
    moment: MatchMoment,
    data: MomentMintUpdate,
) -> MatchMoment:
    """Apply an idempotent client-reported mint receipt."""
    moment.wallet_address = data.wallet_address
    moment.mint_address = data.mint_address
    moment.mint_tx_sig = data.mint_tx_sig
    await db.commit()
    await db.refresh(moment)
    logger.info(
        "moments.mint_updated",
        moment_id=moment.id,
        wallet_address=moment.wallet_address,
        mint_address=moment.mint_address,
    )
    return moment
