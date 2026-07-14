"""HTTP contract tests for public MatchPulse moment routes."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.live.schemas import LiveEventFrame, LiveMatchState
from app.moments.models import MatchMoment
from app.moments.routes import matchpulse_router, router


def _moment(*, card_image_url: str | None = "https://cdn.test/card.png") -> MatchMoment:
    """Build a response-ready moment without database access."""
    return MatchMoment(
        id="moment-1",
        match_id=18237038,
        event_id="txline:18237038:penalty_outcome:213",
        event_type="Shot",
        minute=21,
        description="Oyarzabal converts a penalty for Spain",
        card_image_url=card_image_url,
        txline_seq=221,
        txline_proof_json='{"eventStatRoot":"root"}',
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _event() -> LiveEventFrame:
    """Build the buffered source event used by the POST contract."""
    return LiveEventFrame(
        event_id="txline:18237038:penalty_outcome:213",
        match_id=18237038,
        event_type="Shot",
        minute=21,
        second=53,
        period=1,
        team_id=3021,
        team_name="Spain",
        outcome="Goal",
        event_index=221,
        raw_data={"Participant": 2, "shot_type": "Penalty"},
        source="txline",
    )


def _state() -> LiveMatchState:
    """Build current state for route source validation."""
    return LiveMatchState(
        match_id=18237038,
        home_team="France",
        away_team="Spain",
        home_team_id=1999,
        away_team_id=3021,
        away_score=1,
        minute=21,
        status="live",
        source="txline",
    )


async def _client() -> AsyncIterator[AsyncClient]:
    """Yield an isolated FastAPI client with a mocked database dependency."""
    app = FastAPI()
    app.include_router(router)
    app.include_router(matchpulse_router)
    db = AsyncMock(spec=AsyncSession)

    async def override_db() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_create_moment_endpoint_returns_201() -> None:
    async for client in _client():
        with (
            patch("app.moments.routes._find_buffered_event", new=AsyncMock(return_value=_event())),
            patch(
                "app.moments.routes.LiveMatchStateManager.get_state",
                new=AsyncMock(return_value=_state()),
            ),
            patch("app.moments.routes.service.create_moment", new=AsyncMock(return_value=_moment())),
        ):
            response = await client.post(
                "/api/moments",
                json={
                    "match_id": 18237038,
                    "event_id": "txline:18237038:penalty_outcome:213",
                    "event_type": "Shot",
                    "minute": 21,
                },
            )

    assert response.status_code == 201
    assert response.json()["txline_seq"] == 221


async def test_get_moment_not_found_returns_404() -> None:
    async for client in _client():
        with patch("app.moments.routes.service.get_moment", new=AsyncMock(return_value=None)):
            response = await client.get("/api/moments/missing")

    assert response.status_code == 404


async def test_list_moments_filters_by_match_id() -> None:
    async for client in _client():
        with patch(
            "app.moments.routes.service.list_moments",
            new=AsyncMock(return_value=[_moment()]),
        ) as list_moments:
            response = await client.get("/api/moments?match_id=18237038&limit=10")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert list_moments.await_args.kwargs == {"match_id": 18237038, "limit": 10}


async def test_metadata_endpoint_shape_and_placeholder_fallback() -> None:
    moment = _moment(card_image_url=None)
    async for client in _client():
        with patch("app.moments.routes.service.get_moment", new=AsyncMock(return_value=moment)):
            response = await client.get("/api/moments/moment-1/metadata")

    payload = response.json()
    assert response.status_code == 200
    assert set(payload) == {"name", "description", "image", "attributes"}
    assert payload["image"] == "http://test/api/moments/placeholder.svg"
    traits = {attribute["trait_type"]: attribute["value"] for attribute in payload["attributes"]}
    assert traits["Verified"] == "true"
    assert traits["TxLINE Sequence"] == "221"
    assert traits["TxLINE Proof"] == '{"eventStatRoot":"root"}'


async def test_matchpulse_health_endpoint_counts_recordings(tmp_path: Path) -> None:
    (tmp_path / "hero.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "secondary.jsonl").write_text("{}\n", encoding="utf-8")
    async for client in _client():
        with (
            patch("app.moments.routes.DEFAULT_RECORDING_DIR", tmp_path),
            patch(
                "app.moments.routes.get_settings",
                return_value=type("Settings", (), {"matchpulse_enabled": True})(),
            ),
        ):
            response = await client.get("/api/matchpulse/health")

    assert response.status_code == 200
    assert response.json() == {"matchpulse_enabled": True, "recordings_count": 2}
