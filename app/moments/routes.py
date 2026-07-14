"""Public MatchPulse moment, metadata, and health HTTP routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.live.schemas import LiveEventFrame
from app.live.state_manager import LiveMatchStateManager
from app.live.subscription_manager import LiveEventSubscriptionManager
from app.live.txline.recorder import DEFAULT_RECORDING_DIR
from app.moments import service
from app.moments.models import MatchMoment
from app.moments.schemas import (
    MatchPulseHealthResponse,
    MomentCreate,
    MomentMetadataAttribute,
    MomentMetadataResponse,
    MomentMintUpdate,
    MomentResponse,
)

router = APIRouter(prefix="/api/moments", tags=["moments"])
matchpulse_router = APIRouter(prefix="/api/matchpulse", tags=["matchpulse"])

_PLACEHOLDER_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="675" viewBox="0 0 1200 675"><rect width="1200" height="675" fill="#facc15"/><rect x="30" y="30" width="1140" height="615" fill="none" stroke="#000" stroke-width="16"/><text x="600" y="315" text-anchor="middle" font-family="Arial,sans-serif" font-size="96" font-weight="900">MATCHPULSE</text><text x="600" y="405" text-anchor="middle" font-family="Arial,sans-serif" font-size="42" font-weight="700">VERIFIABLE MATCH MOMENT</text></svg>"""


async def _require_moment(db: AsyncSession, moment_id: str) -> MatchMoment:
    """Load a moment or raise the shared not-found response."""
    moment = await service.get_moment(db, moment_id)
    if moment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Moment not found")
    return moment


async def _find_buffered_event(match_id: int, event_id: str) -> LiveEventFrame | None:
    """Find a source event in the active replay/live processor buffer."""
    processor = LiveEventSubscriptionManager().get_processor(match_id)
    if processor is None:
        return None
    events = await processor.get_recent_events()
    return next((event for event in reversed(events) if event.event_id == event_id), None)


def _public_image_url(request: Request, card_image_url: str | None) -> str:
    """Resolve stored local paths into absolute metadata image URLs."""
    forwarded_scheme = request.headers.get("x-forwarded-proto", "").split(",", maxsplit=1)[0]
    if card_image_url is None:
        placeholder_url = request.url_for("moment_placeholder")
        if forwarded_scheme in {"http", "https"}:
            placeholder_url = placeholder_url.replace(scheme=forwarded_scheme)
        return str(placeholder_url)
    if card_image_url.startswith(("https://", "http://")):
        return card_image_url
    base_url = request.base_url
    if forwarded_scheme in {"http", "https"}:
        base_url = base_url.replace(scheme=forwarded_scheme)
    return f"{str(base_url).rstrip('/')}/{card_image_url.lstrip('/')}"


@router.get("/placeholder.svg", name="moment_placeholder", include_in_schema=False)
async def moment_placeholder() -> Response:
    """Serve a stable public image when best-effort card generation is unavailable."""
    return Response(content=_PLACEHOLDER_SVG, media_type="image/svg+xml")


@router.post("", response_model=MomentResponse, status_code=status.HTTP_201_CREATED)
async def create_moment(
    data: MomentCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MatchMoment:
    """Create a persisted moment from an event in an active replay or live buffer."""
    event = await _find_buffered_event(data.match_id, data.event_id)
    state = await LiveMatchStateManager().get_state(data.match_id)
    if event is None or state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Live/replay event or match state not found",
        )
    if event.event_type != data.event_type or event.minute != data.minute:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Event identity does not match the buffered source event",
        )
    return await service.create_moment(db, data.match_id, event, state)


@router.get("", response_model=list[MomentResponse])
async def get_moments(
    db: Annotated[AsyncSession, Depends(get_db)],
    match_id: int | None = Query(None, description="Optional TxLINE fixture filter"),
    limit: int = Query(50, ge=1, le=100, description="Maximum moments to return"),
) -> list[MatchMoment]:
    """List persisted moments, newest first."""
    return await service.list_moments(db, match_id=match_id, limit=limit)


@router.get("/{moment_id}", response_model=MomentResponse)
async def get_moment(
    moment_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MatchMoment:
    """Get one persisted moment."""
    return await _require_moment(db, moment_id)


@router.patch("/{moment_id}/mint", response_model=MomentResponse)
async def patch_mint(
    moment_id: str,
    data: MomentMintUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MatchMoment:
    """Persist a client-signed Solana mint receipt; retries are last-write-wins."""
    moment = await _require_moment(db, moment_id)
    return await service.update_mint(db, moment, data)


@router.get("/{moment_id}/metadata", response_model=MomentMetadataResponse)
async def get_moment_metadata(
    request: Request,
    moment_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MomentMetadataResponse:
    """Serve public Metaplex-standard off-chain metadata without authentication."""
    moment = await _require_moment(db, moment_id)
    image = _public_image_url(request, moment.card_image_url)
    attributes = [
        MomentMetadataAttribute(trait_type="Match ID", value=str(moment.match_id)),
        MomentMetadataAttribute(trait_type="Minute", value=str(moment.minute)),
        MomentMetadataAttribute(trait_type="Event Type", value=moment.event_type),
        MomentMetadataAttribute(
            trait_type="Verified", value="true" if moment.txline_proof_json else "false"
        ),
    ]
    if moment.txline_seq is not None:
        attributes.append(
            MomentMetadataAttribute(trait_type="TxLINE Sequence", value=str(moment.txline_seq))
        )
    if moment.txline_proof_json is not None:
        attributes.append(
            MomentMetadataAttribute(trait_type="TxLINE Proof", value=moment.txline_proof_json)
        )
    return MomentMetadataResponse(
        name=f"MatchPulse: {moment.description}",
        description=(
            f"A verifiable MatchPulse moment from TxLINE fixture {moment.match_id}. "
            f"{moment.description}."
        ),
        image=image,
        attributes=attributes,
    )


@matchpulse_router.get("/health", response_model=MatchPulseHealthResponse)
async def matchpulse_health() -> MatchPulseHealthResponse:
    """Report feature-flag state and available replay recordings."""
    settings = get_settings()
    recordings_count = (
        sum(1 for _path in DEFAULT_RECORDING_DIR.glob("*.jsonl"))
        if DEFAULT_RECORDING_DIR.is_dir()
        else 0
    )
    return MatchPulseHealthResponse(
        matchpulse_enabled=settings.matchpulse_enabled,
        recordings_count=recordings_count,
    )
