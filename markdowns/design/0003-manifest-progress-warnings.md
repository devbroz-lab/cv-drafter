---
title: 0003 — Real-time progress & warnings on the polled /manifest channel
type: design
status: accepted
owner: backend
last_verified: 2026-06-09
code_refs:
  - pipeline/manifest.py
  - pipeline/validators.py
  - pipeline/orchestrator.py
  - api/models/requests.py
  - api/routers/sessions.py
related:
  - reference/orchestration.md
  - reference/api.md
  - frontend/progress-and-warnings.md
---

# 0003 — Real-time progress & warnings on the polled /manifest channel

## Context

The UI polls `GET /status` and `GET /manifest` (~2.5s, React Query); there is no push channel. But
`ManifestResponse` returned only `steps`/`checkpoint_pending`/`reviewer_blocked` — it dropped the
`warnings[]` array already sitting in `manifest.json`, steps had only `completed_at` (no `started_at`),
and the dedicated `GET /warnings` aggregator was never called by the UI. Several agent warnings
(A1 extraction, A3 alignment, A4 generation, A5 review) lived only in their source artifact files, so
they never reached the polled channel during a run — only end-of-run `generation_warnings`/`review`
surfaced via `/output`.

## Decision

Enrich the already-polled endpoints (no SSE/WebSocket — the frontend is poll-based and out of scope):

- **`/manifest`** gains `steps[].started_at` (stamped on first `running`), `progress` (0–100),
  `current_step`, and `warnings[]`.
- **Backfill** every agent's warnings into `manifest.json` at its phase boundary (readers in
  `pipeline/validators.py`); `append_warning` is now **idempotent** (skips identical
  `stage/kind/message`).
- **`/warnings`** reads manifest-first (per-step `stage`), keeps source-file reads for old sessions,
  and **de-duplicates** by `(kind, message)`.

All additive — the existing UI keeps working; the frontend adopts the new fields when ready.

## Consequences

**Good:** progress + warnings stream on the channel the UI already polls, grouped by step, in real
time. **Bad/cost:** warnings now exist in both the manifest and source files (handled by de-dup);
a little extra orchestrator wiring per phase.

## Alternatives considered

- SSE/WebSocket push — rejected (truer real-time, but requires a frontend rewrite to consume; the
  work would sit unused until the out-of-scope UI adopts it).
- Keep warnings only in `/warnings` and have the UI start polling it — rejected (the UI doesn't poll
  it; nothing would surface without a frontend change).

## Refs

Branch `fix/opus48-oversized-output-lean-agents`, commit `c15bf82`. Tests:
`tests/test_manifest_progress.py`, `tests/test_manifest_warning_backfill.py`.
