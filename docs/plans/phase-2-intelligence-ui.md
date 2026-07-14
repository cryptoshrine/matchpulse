# Phase 2: intelligence and replay UI

## Goal

Convert TxLINE frames into the platform-neutral live event/state contract, replay recorded sessions through the same processing path, and expose an unauthenticated demo page with narrative, score, momentum, and alerts.

## Delivered slices

1. Real-frame event map for phase, score, card, substitution, and penalty actions.
2. Normalizer that retains source identifiers and real `Seq` values.
3. Lightweight momentum model for the data available in the score stream.
4. Accelerated JSONL replay with recording discovery and validation.
5. Dedicated MatchPulse WebSocket and React hook.
6. Neubrutalist replay page with score, story, momentum, and alert components.

## Validation

Golden fixture tests exercise the end-to-end normalization contract. Browser verification checks replay start, incremental notifications, state snapshots, reconnect behavior, and bounded feed rendering.
