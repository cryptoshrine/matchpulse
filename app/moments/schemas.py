"""Pydantic request and response schemas for MatchPulse moments."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MomentCreate(BaseModel):
    """Identify a buffered live/replay event to turn into a moment."""

    match_id: int = Field(..., description="TxLINE fixture identifier")
    event_id: str = Field(..., min_length=1, max_length=128, description="Live event ID")
    event_type: str = Field(..., min_length=1, max_length=50, description="Live event type")
    minute: int = Field(..., ge=0, le=120, description="Match minute")


class MomentResponse(BaseModel):
    """Public persisted moment fields, excluding the large proof payload."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Moment UUID")
    match_id: int = Field(..., description="TxLINE fixture identifier")
    event_id: str = Field(..., description="Live event identifier")
    event_type: str = Field(..., description="Provider-neutral event type")
    minute: int = Field(..., description="Match minute")
    description: str = Field(..., description="Human-readable moment description")
    card_image_url: str | None = Field(None, description="Generated card image URL")
    txline_seq: int | None = Field(None, description="Real TxLINE frame sequence")
    wallet_address: str | None = Field(None, description="Minting wallet public address")
    mint_address: str | None = Field(None, description="Metaplex Core asset address")
    mint_tx_sig: str | None = Field(None, description="Solana mint transaction signature")
    created_at: datetime = Field(..., description="Moment creation timestamp")


class MomentMintUpdate(BaseModel):
    """Client-reported result of a successfully signed on-chain mint."""

    wallet_address: str = Field(
        ..., min_length=32, max_length=64, description="Signing wallet public address"
    )
    mint_address: str = Field(
        ..., min_length=32, max_length=64, description="Metaplex Core asset address"
    )
    mint_tx_sig: str = Field(
        ..., min_length=64, max_length=128, description="Solana transaction signature"
    )


class MomentMetadataAttribute(BaseModel):
    """One Metaplex-compatible metadata trait."""

    trait_type: str = Field(..., description="Trait label")
    value: str = Field(..., description="Trait value")


class MomentMetadataResponse(BaseModel):
    """Public Metaplex-standard off-chain metadata document."""

    name: str = Field(..., description="Collectible display name")
    description: str = Field(..., description="Collectible description")
    image: str = Field(..., description="Public card image URL")
    attributes: list[MomentMetadataAttribute] = Field(..., description="Moment traits")


class MatchPulseHealthResponse(BaseModel):
    """Judge-facing MatchPulse availability response."""

    matchpulse_enabled: bool = Field(..., description="Backend feature-flag state")
    recordings_count: int = Field(..., ge=0, description="Available JSONL replay recordings")
