"""Public MatchPulse recording discovery and replay controls."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeGuard, cast

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.core.logging import get_logger
from app.live.state_manager import LiveMatchStateManager
from app.live.subscription_manager import LiveEventSubscriptionManager
from app.live.txline.recorder import DEFAULT_RECORDING_DIR

logger = get_logger(__name__)
router = APIRouter(prefix="/api/matchpulse", tags=["matchpulse-replay"])


class ReplayRequest(BaseModel):
    """Request to replay one local TxLINE recording."""

    match_id: int = Field(..., description="TxLINE fixture identifier")
    recording_file: str = Field(..., min_length=1, description="Bare JSONL filename")
    speed: float = Field(default=10.0, ge=0.1, le=60.0, description="Playback speed")
    home_team: str | None = Field(default=None, description="Fallback home team name")
    away_team: str | None = Field(default=None, description="Fallback away team name")
    home_team_id: int | None = Field(default=None, description="Fallback home team identifier")
    away_team_id: int | None = Field(default=None, description="Fallback away team identifier")

    @field_validator("recording_file")
    @classmethod
    def validate_recording_file(cls, value: str) -> str:
        """Reject traversal and directory components before filesystem access."""
        if ".." in value or "/" in value or "\\" in value or Path(value).name != value:
            raise ValueError("recording_file must be a bare filename")
        return value


class ReplayResponse(BaseModel):
    """Response describing a replay session."""

    status: str
    match_id: int
    events_received: int = 0
    message: str


class RecordingInfo(BaseModel):
    """Metadata used by the MatchPulse recording picker."""

    filename: str
    size_bytes: int
    match_id: int | None = None
    home_team: str | None = None
    away_team: str | None = None
    home_team_id: int | None = None
    away_team_id: int | None = None


class RecordingsResponse(BaseModel):
    """Available TxLINE recordings response."""

    recordings: list[RecordingInfo]
    count: int


def _as_dict(value: Any) -> dict[str, Any]:
    """Return JSON-like object values as a typed dictionary."""
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in cast(dict[object, Any], value).items()}


def _as_int(value: Any) -> int | None:
    """Return integer provider values without coercing booleans."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _is_any_list(value: object) -> TypeGuard[list[Any]]:
    """Narrow JSON arrays to a strict ``list[Any]``."""
    return isinstance(value, list)


def _sidecar_metadata(path: Path, match_id: int | None) -> dict[str, Any]:
    """Read Phase 1 sidecar metadata when present."""
    sidecar = Path(f"{path}.meta.json")
    if not sidecar.is_file():
        return {}
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    typed_payload = _as_dict(payload)
    fixtures = typed_payload.get("fixtures")
    if _is_any_list(fixtures):
        for fixture in fixtures:
            item = _as_dict(fixture)
            if match_id is None or _as_int(item.get("fixture_id")) == match_id:
                return item
        return {}
    return _as_dict(payload)


def _recording_metadata(path: Path, match_id: int | None = None) -> dict[str, Any]:
    """Resolve teams from sidecar metadata or in-band TxLINE lineups."""
    sidecar = _sidecar_metadata(path, match_id)
    if sidecar:
        participant1_id = _as_int(sidecar.get("participant1_id"))
        participant2_id = _as_int(sidecar.get("participant2_id"))
        participant1_home = sidecar.get("participant1_is_home") is not False
        return {
            "match_id": _as_int(sidecar.get("fixture_id")) or match_id,
            "home_team": sidecar.get("participant1")
            if participant1_home
            else sidecar.get("participant2"),
            "away_team": sidecar.get("participant2")
            if participant1_home
            else sidecar.get("participant1"),
            "home_team_id": participant1_id if participant1_home else participant2_id,
            "away_team_id": participant2_id if participant1_home else participant1_id,
        }

    team_names: dict[int, str] = {}
    base: dict[str, Any] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for line in lines:
        try:
            envelope = json.loads(line)
        except json.JSONDecodeError:
            continue
        raw = _as_dict(_as_dict(envelope).get("data"))
        raw_match_id = _as_int(raw.get("FixtureId")) or _as_int(raw.get("fixtureId"))
        if match_id is not None and raw_match_id is not None and raw_match_id != match_id:
            continue
        if not base and raw_match_id is not None:
            base = raw
        lineups = raw.get("Lineups") or raw.get("lineups")
        if not _is_any_list(lineups):
            continue
        base = raw
        for team_value in lineups:
            team = _as_dict(team_value)
            team_id = _as_int(team.get("normativeId"))
            team_name = team.get("preferredName")
            if team_id is not None and isinstance(team_name, str):
                team_names[team_id] = team_name
        if len(team_names) >= 2:
            break

    participant1_id = _as_int(base.get("Participant1Id")) or _as_int(base.get("participant1Id"))
    participant2_id = _as_int(base.get("Participant2Id")) or _as_int(base.get("participant2Id"))
    participant1_home = base.get("Participant1IsHome", base.get("participant1IsHome")) is not False
    home_team_id = participant1_id if participant1_home else participant2_id
    away_team_id = participant2_id if participant1_home else participant1_id
    return {
        "match_id": _as_int(base.get("FixtureId")) or _as_int(base.get("fixtureId")) or match_id,
        "home_team": team_names.get(home_team_id) if home_team_id is not None else None,
        "away_team": team_names.get(away_team_id) if away_team_id is not None else None,
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
    }


@router.get("/recordings", response_model=RecordingsResponse)
async def list_recordings() -> RecordingsResponse:
    """List replayable JSONL recordings and best-effort team metadata."""
    recordings: list[RecordingInfo] = []
    if DEFAULT_RECORDING_DIR.is_dir():
        for path in sorted(DEFAULT_RECORDING_DIR.glob("*.jsonl")):
            metadata = _recording_metadata(path)
            recordings.append(
                RecordingInfo(
                    filename=path.name,
                    size_bytes=path.stat().st_size,
                    match_id=metadata.get("match_id"),
                    home_team=metadata.get("home_team"),
                    away_team=metadata.get("away_team"),
                    home_team_id=metadata.get("home_team_id"),
                    away_team_id=metadata.get("away_team_id"),
                )
            )
    return RecordingsResponse(recordings=recordings, count=len(recordings))


@router.post("/replay", response_model=ReplayResponse)
async def start_replay(request: ReplayRequest) -> ReplayResponse:
    """Initialize match state and start one replay-backed subscription."""
    path = (DEFAULT_RECORDING_DIR / request.recording_file).resolve()
    root = DEFAULT_RECORDING_DIR.resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status_code=404, detail="Recording not found")

    metadata = _recording_metadata(path, request.match_id)
    home_team_id = request.home_team_id or metadata.get("home_team_id") or 1
    away_team_id = request.away_team_id or metadata.get("away_team_id") or 2
    home_team = request.home_team or metadata.get("home_team") or f"Team {home_team_id}"
    away_team = request.away_team or metadata.get("away_team") or f"Team {away_team_id}"

    logger.info(
        "matchpulse.replay.start_requested",
        match_id=request.match_id,
        recording_file=request.recording_file,
        speed=request.speed,
    )
    state_manager = LiveMatchStateManager()
    await state_manager.initialize_match(
        match_id=request.match_id,
        home_team=str(home_team),
        away_team=str(away_team),
        home_team_id=int(home_team_id),
        away_team_id=int(away_team_id),
        source="txline",
    )
    subscription_manager = LiveEventSubscriptionManager()
    started = await subscription_manager.start_subscription(
        match_id=request.match_id,
        source="txline",
        replay=True,
        recording_file=str(path),
        speed=request.speed,
    )
    if not started:
        raise HTTPException(status_code=409, detail="Replay is already running")
    return ReplayResponse(
        status="started",
        match_id=request.match_id,
        message=f"Replay started at {request.speed:g}x speed",
    )


@router.get("/replay/{match_id}", response_model=ReplayResponse)
async def get_replay_status(match_id: int) -> ReplayResponse:
    """Return live replay status and processed-event count."""
    manager = LiveEventSubscriptionManager()
    processor = manager.get_processor(match_id)
    if processor is None:
        raise HTTPException(status_code=404, detail=f"No replay found for match {match_id}")
    running = manager.is_subscribed(match_id)
    status = "running" if running else "completed"
    return ReplayResponse(
        status=status,
        match_id=match_id,
        events_received=processor.events_processed,
        message=f"Replay {status} - {processor.events_processed} events",
    )


@router.delete("/replay/{match_id}", response_model=ReplayResponse)
async def stop_replay(match_id: int) -> ReplayResponse:
    """Cancel an active replay subscription."""
    manager = LiveEventSubscriptionManager()
    processor = manager.get_processor(match_id)
    events_received = processor.events_processed if processor is not None else 0
    stopped = await manager.stop_subscription(match_id)
    if not stopped:
        raise HTTPException(status_code=404, detail=f"No active replay for match {match_id}")
    return ReplayResponse(
        status="stopped",
        match_id=match_id,
        events_received=events_received,
        message="Replay stopped",
    )
