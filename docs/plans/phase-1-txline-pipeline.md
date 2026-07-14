# Phase 1: TxLINE pipeline

## Goal

Create a typed, reconnectable TxLINE ingestion path that can discover fixtures, consume score SSE, recover missed frames over REST, and record replayable JSONL without coupling downstream intelligence to a provider wire format.

## Delivered slices

1. Network-aware guest activation and request headers.
2. Permissive wire schemas that preserve unmodeled fields.
3. REST helpers for fixtures, snapshots, updates, historical frames, and stat validation.
4. SSE parsing with multiline data, last-event resume, and reconnect handling.
5. Atomic JSONL recording plus sidecar match metadata.
6. Focused unit tests with no full match dump committed.

## Validation

The client, parser, recorder, auth, and schema suites cover transport recovery and forward-compatible payload parsing. Real recordings are retained only in the private deployment environment.
