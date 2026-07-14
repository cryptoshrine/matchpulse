-- MatchPulse Phase 3: persisted collectible moments and mint receipts
-- Migration: 022_create_match_moments.sql

CREATE TABLE IF NOT EXISTS match_moments (
    id VARCHAR(36) PRIMARY KEY,
    match_id INTEGER NOT NULL,
    event_id VARCHAR(64) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    minute INTEGER NOT NULL,
    description VARCHAR(500) NOT NULL,
    card_image_url VARCHAR(500),
    txline_seq INTEGER,
    txline_proof_json TEXT,
    wallet_address VARCHAR(64),
    mint_address VARCHAR(64),
    mint_tx_sig VARCHAR(128),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_match_moments_match_id ON match_moments(match_id);
CREATE INDEX IF NOT EXISTS idx_match_moments_wallet_address
    ON match_moments(wallet_address) WHERE wallet_address IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_match_moments_mint_address
    ON match_moments(mint_address) WHERE mint_address IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_match_moments_match_event
    ON match_moments(match_id, event_id);

CREATE OR REPLACE FUNCTION update_match_moments_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_match_moments_updated_at ON match_moments;
CREATE TRIGGER trigger_match_moments_updated_at
    BEFORE UPDATE ON match_moments
    FOR EACH ROW
    EXECUTE FUNCTION update_match_moments_updated_at();

ALTER TABLE match_moments ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Public can read match moments" ON match_moments;
CREATE POLICY "Public can read match moments"
    ON match_moments
    FOR SELECT
    USING (true);
