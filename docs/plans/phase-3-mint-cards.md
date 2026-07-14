# Phase 3: verifiable moment cards and ship

## Goal

Turn a replay event into a persisted fan moment with a TxLINE Merkle proof, public collectible metadata, and an optional Phantom-signed Metaplex Core asset on Solana devnet.

## Delivered slices

1. Revision-aware goal attribution so late player data enriches the story without a duplicate score.
2. `MatchMoment` storage, migration, API schemas, and idempotent mint receipt updates.
3. Stat-major key selection and proof requests using real recorded sequence values.
4. Best-effort card rendering with a deterministic public fallback image.
5. Public Metaplex-compatible metadata.
6. Route-scoped wallet providers and mint UI in the lazy MatchPulse page bundle.
7. Production recordings volume and build-time feature-flag wiring.

## Validation

Backend tests cover proof failure, disabled rendering, metadata fallback, mint retry, stat keys, and late scorer attribution. Frontend gates are TypeScript, targeted lint, production build, and a real Phantom/devnet approval in the deployed browser.
