# MatchPulse technical notes

## TxLINE endpoints used

Base URLs are selected by network:

- Mainnet: `https://txline.txodds.com/api`
- Devnet: `https://txline-dev.txodds.com/api`

The feature uses these operations:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/auth/guest/start` | Start a guest session. |
| `POST` | `/api/token/activate` | Activate the selected subscription on the chosen network. |
| `GET` | `/api/fixtures/snapshot` | Discover fixtures and participant metadata. |
| `GET` | `/api/scores/stream` | Consume live score frames over SSE. |
| `GET` | `/api/scores/snapshot/{fixtureId}` | Load a score snapshot, optionally as of a timestamp. |
| `GET` | `/api/scores/updates/{fixtureId}` | Recover score updates for a fixture. |
| `GET` | `/api/scores/historical/{fixtureId}` | Recover historical frames for replay. |
| `GET` | `/api/scores/stat-validation-v3` | Fetch the Merkle multiproof for selected fixture stats. |

`stat-validation-v3` is called with `fixtureId`, a real frame `seq >= 1`, and one to five comma-separated `statKeys`. MatchPulse never fabricates a sequence value. Soccer stats are stat-major: keys `1/2` are participant-one/two goals, `3/4` yellows, `5/6` reds, and `7/8` corners. Period prefixes such as `1000` and `2000` are combined with the base key when the proof needs a period-specific stat.

## Stream behavior

The SSE client sends `Authorization`, `X-Api-Token`, `Accept: text/event-stream`, and `Cache-Control: no-cache`. It parses `id`, `event`, and multiline `data` fields, reconnects after transient transport failures, and resumes with the last observed SSE identifier.

Recorded envelopes retain reception time, SSE metadata, and the untouched TxLINE data frame. Replay reads the same JSONL shape and can run at accelerated speed without changing downstream event processing.

## Normalization decisions

- `StatusId` is authoritative for live phase. The source `GameState` value is retained but is not rewritten.
- `Seq` becomes `LiveEventFrame.event_index` and later feeds proof generation.
- Event identities are derived from fixture, action, and TxLINE `Id`.
- A first valid scoring revision emits the canonical scoring event.
- A later same-identity frame emits an amendment only when it adds meaningful attribution, such as a player identifier or player name.
- Amendments are explicitly non-scoring, reference the canonical event, and produce an updated narrative notification.

## Moment and mint flow

1. The browser posts the chosen replay event to `POST /api/moments`.
2. The service persists the event and match snapshot, requests a TxLINE proof with the frame's real `Seq`, and attempts a moment-card render.
3. `GET /api/moments/{id}/metadata` returns public Metaplex-style JSON with the match, minute, event type, sequence, and proof-verification attributes.
4. The MatchPulse page creates a Umi client on Solana devnet and bridges the connected Phantom wallet.
5. Metaplex Core `create(umi, { asset, name, uri })` creates the asset; the metadata endpoint is its `uri`.
6. The browser patches the wallet address, asset address, and transaction signature to `PATCH /api/moments/{id}/mint`.

Proof and card rendering are best-effort by design. A temporary external failure produces a usable persisted moment with an explicit unverified or image-fallback state instead of a match-time HTTP failure.
