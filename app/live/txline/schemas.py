"""Permissive raw-payload schemas for the TxLINE API."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TxLineScoresMessage(BaseModel):
    """One raw TxLINE scores message.

    Every field is optional because TxLINE's ``Scores`` payload is
    sport-polymorphic and has no worked football example. MatchPulse recordings
    provide the ground truth used to tighten this model in Phase 2.
    """

    model_config = ConfigDict(extra="allow")

    fixtureId: int | None = Field(default=None, description="TxLINE fixture identifier")
    gameState: int | str | None = Field(default=None, description="Provider game-state value")
    startTime: int | str | None = Field(default=None, description="Fixture start time")
    isTeam: bool | None = Field(default=None, description="Whether participants are teams")
    fixtureGroupId: int | None = Field(default=None, description="Fixture group identifier")
    competitionId: int | None = Field(default=None, description="Competition identifier")
    countryId: int | None = Field(default=None, description="Country identifier")
    sportId: int | None = Field(default=None, description="Sport identifier")
    participant1IsHome: bool | None = Field(
        default=None, description="Whether participant one is the home side"
    )
    participant1Id: int | None = Field(default=None, description="Participant one identifier")
    participant2Id: int | None = Field(default=None, description="Participant two identifier")
    action: str | None = Field(default=None, description="Scores action name")
    id: str | int | None = Field(default=None, description="Provider message identifier")
    ts: int | None = Field(default=None, description="Provider event timestamp")
    connectionId: str | None = Field(default=None, description="SSE connection identifier")
    seq: int | None = Field(default=None, description="Provider sequence number")


class TxLineFixture(BaseModel):
    """One fixture returned by the TxLINE fixtures snapshot endpoint."""

    model_config = ConfigDict(extra="allow")

    FixtureId: int = Field(..., description="TxLINE fixture identifier")
    Ts: int | None = Field(default=None, description="Snapshot timestamp in epoch milliseconds")
    StartTime: int | str | None = Field(
        default=None, description="Fixture start time, normally epoch milliseconds"
    )
    Competition: str | None = Field(default=None, description="Competition name")
    CompetitionId: int | None = Field(default=None, description="Competition identifier")
    FixtureGroupId: int | None = Field(default=None, description="Fixture group identifier")
    Participant1Id: int | None = Field(default=None, description="Participant one identifier")
    Participant1: str | None = Field(default=None, description="Participant one name")
    Participant2Id: int | None = Field(default=None, description="Participant two identifier")
    Participant2: str | None = Field(default=None, description="Participant two name")
    Participant1IsHome: bool | None = Field(
        default=None, description="Whether participant one is the home side"
    )
    GameState: int | None = Field(default=None, description="Optional fixture game-state value")


class TxLineOddsPayload(BaseModel):
    """One raw TxLINE odds payload, reserved for a later MatchPulse phase."""

    model_config = ConfigDict(extra="allow")

    FixtureId: int = Field(..., description="TxLINE fixture identifier")
    MessageId: str | None = Field(default=None, description="Provider message identifier")
    Ts: int | None = Field(default=None, description="Provider timestamp")
    Bookmaker: str | None = Field(default=None, description="Bookmaker name")
    BookmakerId: int | None = Field(default=None, description="Bookmaker identifier")
    SuperOddsType: str | None = Field(default=None, description="Odds type")
    GameState: int | str | None = Field(default=None, description="Provider game-state value")
    InRunning: bool | None = Field(default=None, description="Whether the market is live")
    MarketParameters: dict[str, Any] | None = Field(
        default=None, description="Market-specific parameters"
    )
    MarketPeriod: str | None = Field(default=None, description="Market period")
    PriceNames: list[str] | None = Field(default=None, description="Price labels")
    Prices: list[float] | None = Field(default=None, description="Market prices")
    Pct: float | None = Field(default=None, description="Provider percentage value")
