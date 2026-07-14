"""Database model for persisted MatchPulse collectible moments."""

import uuid

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin


class MatchMoment(Base, TimestampMixin):
    """One replay or live-match event prepared for collectible minting.

    Attributes:
        id: UUID primary key.
        match_id: TxLINE fixture identifier.
        event_id: Canonical provider-neutral live event identifier.
        event_type: Provider-neutral event type.
        minute: Match minute for display.
        description: Human-readable moment description.
        card_image_url: Best-effort generated card URL.
        txline_seq: Real provider sequence used for the proof.
        txline_proof_json: Opaque serialized TxLINE Merkle multiproof.
        wallet_address: Public wallet that signed the mint.
        mint_address: Metaplex Core asset address.
        mint_tx_sig: Solana transaction signature.
        created_at: Creation timestamp from ``TimestampMixin``.
        updated_at: Last-update timestamp from ``TimestampMixin``.
    """

    __tablename__ = "match_moments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    match_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    minute: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    card_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    txline_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    txline_proof_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    wallet_address: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    mint_address: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    mint_tx_sig: Mapped[str | None] = mapped_column(String(128), nullable=True)

    def __repr__(self) -> str:
        """Return a compact debugging representation."""
        return (
            f"<MatchMoment(id={self.id}, match_id={self.match_id}, "
            f"event_id={self.event_id}, mint_address={self.mint_address})>"
        )
