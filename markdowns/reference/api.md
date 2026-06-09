---
title: HTTP API Surface
type: reference
status: current
owner: backend
last_verified: 2026-06-08
code_refs:
  - api/routers/sessions.py
  - api/models/requests.py
  - api/services/database.py
related:
  - reference/orchestration.md
  - frontend/progress-and-warnings.md
---

# HTTP API Surface

FastAPI router `api/routers/sessions.py`; response models in `api/models/requests.py`. All session
routes require `Authorization: Bearer <Supabase JWT>` (except `GET /health`). Transport is
**poll-only** — no WebSocket/SSE.

## Lifecycle endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/sessions` | Create a session (`target_format`, `source_filename`, optional job metadata) |
| POST | `/sessions/{id}/upload/source` | Upload CV (`.docx`/`.pdf`) |
| POST | `/sessions/{id}/upload/tor` | Upload ToR (optional) |
| POST | `/sessions/{id}/start` | `queued` → schedule Phase 1 (returns immediately, `processing`) |
| POST | `/sessions/{id}/tor/select-pool` | Prune ToR pools to the chosen one (index 0) |
| POST | `/sessions/{id}/approve/{checkpoint}` | Approve `checkpoint_1\|2\|3`; schedule the next phase |
| POST | `/sessions/{id}/resolve` | Clear a reviewer block / apply overrides; resume A6 |
| POST | `/sessions/{id}/field-edit` | Post-completion targeted edits (synchronous; → `checkpoint_3_pending`) |

## Read / polling endpoints

| Method | Path | Returns |
|--------|------|---------|
| GET | `/sessions/{id}/status` | `SessionStatusResponse` — coarse status, round, filenames, `download_url` when completed, `error_message` when failed |
| GET | `/sessions/{id}/manifest` | `ManifestResponse` — see below |
| GET | `/sessions/{id}/warnings` | `WarningsResponse` — all agent warnings, de-duped, per-step `stage` + counts |
| GET | `/sessions/{id}/review` | `ReviewResponse` — `high_severity[]`, `low_severity[]`, `passed`, `generation_warnings[]` |
| GET | `/sessions/{id}/output` | `OutputResponse` — `cv_data`, `generation_warnings[]`, `review`, `compression` |
| GET | `/sessions/{id}/tor/pools` | `TorPoolsResponse` — pools + `selected_pool_index` |
| GET | `/sessions/{id}/files/output/download-url` | Signed URL for `output.docx` |

## `ManifestResponse` (the primary progress signal)

```jsonc
{
  "session_id": "…",
  "db_status": "processing",
  "steps": [ { "name": "cv_extractor", "status": "done",
               "started_at": "…", "completed_at": "…" } ],
  "checkpoint_pending": "checkpoint_2",   // or null
  "reviewer_blocked": false,
  "progress": 68,                         // 0..100, derived from step statuses
  "current_step": "fields_generator",     // step in flight, or null
  "warnings": [ { "stage": "cv_extractor", "kind": "extraction_warning",
                  "message": "…", "details": null } ]
}
```

`progress`, `current_step`, `steps[].started_at`, and `warnings[]` are additive — the UI polls this
every ~2.5s. Warnings accumulate progressively (extraction by checkpoint 1, alignment by checkpoint 2,
generation/review by checkpoint 3), each tagged with its step `stage`. Full consumer guidance is in
`frontend/progress-and-warnings.md`.

## Status state machine

`SessionStatus` (`api/models/requests.py`): `queued`, `processing`, `checkpoint_1_pending`,
`checkpoint_2_pending`, `checkpoint_3_pending`, `completed`, `failed` (`reviewer_blocked` and
`field_editor_pending` exist for back-compat but new runs don't enter them). Transitions are driven by
the orchestrator via the `api/services/database.py` setters — see `reference/orchestration.md`.

## Notes

- `POST /field-edit` is the supported revision path; `POST /comments` is **deprecated** (emits
  `Deprecation: true`, does not increment `round`).
- Rate limit: max 3 concurrent active sessions per user (active = non-terminal status).
- `GET /output` returns the JSON data, **not** the Word file — download the `.docx` via the signed-URL
  route.
