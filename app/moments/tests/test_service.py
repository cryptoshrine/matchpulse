"""Unit tests for best-effort MatchPulse moment creation."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.ext.asyncio import AsyncSession

from app.live.schemas import LiveEventFrame, LiveMatchState
from app.moments import service


def _penalty_event(*, seq: int | None = 221) -> LiveEventFrame:
    """Build the canonical real-shape Spain penalty event."""
    return LiveEventFrame(
        event_id="txline:18237038:penalty_outcome:213",
        match_id=18237038,
        event_type="Shot",
        minute=21,
        second=53,
        period=1,
        team_id=3021,
        team_name="Spain",
        player_id=463984,
        player_name="Oyarzabal Ugarte, Mikel",
        outcome="Goal",
        event_index=seq,
        raw_data={"Participant": 2, "shot_type": "Penalty"},
        source="txline",
    )


def _match_state() -> LiveMatchState:
    """Build match state immediately after the penalty."""
    return LiveMatchState(
        match_id=18237038,
        home_team="France",
        away_team="Spain",
        home_team_id=1999,
        away_team_id=3021,
        home_score=0,
        away_score=1,
        minute=21,
        period=1,
        status="live",
        source="txline",
    )


def _mock_db(existing: object | None = None) -> AsyncMock:
    """Return an async session mock with synchronous ``add``.

    By default the duplicate-check query finds no existing moment. Pass
    ``existing`` to simulate a moment already persisted for this event.
    """
    db = AsyncMock(spec=AsyncSession)
    db.add = MagicMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = existing
    db.execute.return_value = execute_result
    return db


async def test_create_moment_success_uses_real_sequence_and_stat_major_keys() -> None:
    db = _mock_db()
    proof = {"eventStatRoot": "root", "hashes": ["hash"]}

    with (
        patch("app.moments.service._render_card", new=AsyncMock(return_value="https://card")),
        patch("app.moments.service._fetch_txline_proof", new=AsyncMock(return_value=proof)) as fetch,
    ):
        moment = await service.create_moment(db, 18237038, _penalty_event(), _match_state())

    assert moment.card_image_url == "https://card"
    assert moment.txline_seq == 221
    assert moment.txline_proof_json == '{"eventStatRoot":"root","hashes":["hash"]}'
    fetch.assert_awaited_once_with(fixture_id=18237038, seq=221, stat_keys=["2", "1002"])
    db.add.assert_called_once_with(moment)
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(moment)


async def test_create_moment_idempotent_returns_existing() -> None:
    """A moment already exists for this event (e.g. minted on a prior replay).

    create_moment must return it instead of re-inserting (which violates the
    unique constraint and 500s) or re-rendering the ~30s card.
    """
    existing = service.MatchMoment(
        id="existing-1",
        match_id=18237038,
        event_id="txline:18237038:penalty_outcome:213",
        event_type="Shot",
        minute=21,
        description="Oyarzabal Ugarte, Mikel converts a penalty for Spain in the 21' minute",
    )
    db = _mock_db(existing=existing)

    with (
        patch("app.moments.service._render_card", new=AsyncMock()) as render,
        patch("app.moments.service._fetch_txline_proof", new=AsyncMock()) as fetch,
    ):
        moment = await service.create_moment(db, 18237038, _penalty_event(), _match_state())

    assert moment is existing
    render.assert_not_awaited()
    fetch.assert_not_awaited()
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


async def test_create_moment_proof_fetch_fails_gracefully() -> None:
    db = _mock_db()

    with (
        patch("app.moments.service._render_card", new=AsyncMock(return_value="https://card")),
        patch(
            "app.moments.service._fetch_txline_proof",
            new=AsyncMock(side_effect=RuntimeError("proof unavailable")),
        ),
    ):
        moment = await service.create_moment(db, 18237038, _penalty_event(), _match_state())

    assert moment.card_image_url == "https://card"
    assert moment.txline_seq is None
    assert moment.txline_proof_json is None
    db.commit.assert_awaited_once()


async def test_create_moment_card_render_failure_is_non_fatal() -> None:
    db = _mock_db()

    with (
        patch(
            "app.moments.service._render_card",
            new=AsyncMock(side_effect=RuntimeError("budget exceeded")),
        ),
        patch("app.moments.service._fetch_txline_proof", new=AsyncMock(return_value={})),
    ):
        moment = await service.create_moment(db, 18237038, _penalty_event(), _match_state())

    assert moment.card_image_url is None
    db.commit.assert_awaited_once()


async def test_render_card_disabled_skips_generator() -> None:
    with (
        patch(
            "app.moments.service.get_settings",
            return_value=SimpleNamespace(ai_infographic_enabled=False),
        ),
        patch("app.moments.service.create_infographic_generator") as generator,
    ):
        result = await service._render_card(_penalty_event(), _match_state(), "description")

    assert result is None
    generator.assert_not_called()


async def test_render_card_unconfigured_skips_generation() -> None:
    """Missing image provider configuration degrades to a proof-only moment."""
    with (
        patch(
            "app.moments.service.get_settings",
            return_value=SimpleNamespace(ai_infographic_enabled=True),
        ),
        patch("app.moments.service.create_infographic_generator", return_value=None),
    ):
        result = await service._render_card(_penalty_event(), _match_state(), "description")

    assert result is None


async def test_render_card_credits_txline_attribution() -> None:
    """Moment cards must credit TxODDS TxLINE, not StatsBomb (licensing)."""
    generator = SimpleNamespace(
        generate=AsyncMock(return_value={"file_path": "https://cdn.example/card.png"})
    )
    with (
        patch(
            "app.moments.service.get_settings",
            return_value=SimpleNamespace(ai_infographic_enabled=True),
        ),
        patch("app.moments.service.create_infographic_generator", return_value=generator),
    ):
        result = await service._render_card(_penalty_event(), _match_state(), "description")

    assert result == "https://cdn.example/card.png"
    assert generator.generate.await_args is not None
    assert generator.generate.await_args.kwargs["data_attribution"] == "TxODDS TxLINE"
    # Cards are minted; they must be capped for NFT preview proxies.
    assert generator.generate.await_args.kwargs["max_dimension"] == 1200
    comparison = generator.generate.await_args.kwargs["data"]["comparison_data"]
    assert comparison["home_team"] == _match_state().home_team
    assert comparison["away_team"] == _match_state().away_team


async def test_missing_real_sequence_skips_proof_fetch() -> None:
    db = _mock_db()

    with (
        patch("app.moments.service._render_card", new=AsyncMock(return_value=None)),
        patch("app.moments.service._fetch_txline_proof", new=AsyncMock()) as fetch,
    ):
        moment = await service.create_moment(
            db,
            18237038,
            _penalty_event(seq=None),
            _match_state(),
        )

    assert moment.txline_seq is None
    fetch.assert_not_awaited()


async def test_update_mint_is_idempotent_last_write_wins() -> None:
    db = _mock_db()
    moment = service.MatchMoment(
        id="moment-1",
        match_id=18237038,
        event_id="event-1",
        event_type="Shot",
        minute=21,
        description="Penalty",
    )
    first = service.MomentMintUpdate(
        wallet_address="1" * 32,
        mint_address="2" * 32,
        mint_tx_sig="3" * 64,
    )
    retry = service.MomentMintUpdate(
        wallet_address="4" * 32,
        mint_address="5" * 32,
        mint_tx_sig="6" * 64,
    )

    await service.update_mint(db, moment, first)
    await service.update_mint(db, moment, retry)

    assert moment.wallet_address == retry.wallet_address
    assert moment.mint_address == retry.mint_address
    assert moment.mint_tx_sig == retry.mint_tx_sig
    assert db.commit.await_count == 2
