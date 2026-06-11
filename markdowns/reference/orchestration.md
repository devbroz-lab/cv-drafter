---
title: Orchestration — Phases, Status, Manifest
type: reference
status: current
owner: backend
last_verified: 2026-06-09
code_refs:
  - pipeline/orchestrator.py
  - pipeline/manifest.py
  - pipeline/validators.py
  - api/services/database.py
related:
  - reference/pipeline-overview.md
  - reference/api.md
  - design/0003-manifest-progress-warnings.md
---

# Orchestration

`pipeline/orchestrator.py` runs the pipeline as four phases, each a FastAPI background task. Between
phases the pipeline halts and the DB status becomes `checkpoint_N_pending`; the matching
`POST /approve/checkpoint_N` schedules the next phase. There is **no push channel** — clients poll.

## Phases

| Phase | Entry | Work | Halts at |
|-------|-------|------|----------|
| 1 | `run_phase1` | extract CV text (fail-fast on parse/low-yield); A1 + A2 in parallel (`ThreadPoolExecutor`) | `checkpoint_1_pending` |
| 2 | `run_phase2` | A3 (`cv_tor_mapper`) | `checkpoint_2_pending` |
| 3 | `run_phase3` | A4 → post-A4 hard-block validator → A5 (non-blocking) → A6 | `checkpoint_3_pending` |
| 3-resume | `run_phase3_resume` | A6 only — used by `POST /resolve` after a reviewer block | `checkpoint_3_pending` |
| 4 | `run_phase4` | renderer → upload `output.docx` → `completed` | — |

Each phase calls `set_processing()` first and `set_failed()` in its `except`. Idempotency:
`_run_if_needed()` skips an agent whose manifest step is already `done` (so re-scheduled phases don't
re-run completed work).

Phase 1 also creates the run dir + manifest **before** text extraction, so extraction warnings can be
streamed onto the manifest. CV extraction is guarded: a parse failure or low-yield CV stops Phase 1
with a clear message; the mandatory CV is never fed empty to A1. ToR is best-effort.

## Coarse status — the DB state machine

`sessions.status` (`SessionStatus` in `api/models/requests.py`), set by the helpers in
`api/services/database.py` (`set_processing`, `set_checkpoint_pending`, `set_done`, `set_failed`):

```
queued → processing → checkpoint_1_pending → processing → checkpoint_2_pending
       → processing → checkpoint_3_pending → processing → completed
any phase → failed
```

`status` stays `processing` across all of Phase 2/3/4 — it does **not** identify the running agent;
the manifest does. `reviewer_blocked` and `field_editor_pending` remain valid DB values but are
**not** entered by new runs (the reviewer is non-blocking; field edits go straight to
`checkpoint_3_pending`).

On startup, `reset_stale_processing_sessions` marks rows stuck in `processing` as `failed` so a crash
or redeploy never leaves a session frozen.

## Fine status — the manifest

`runs/{session_id}/manifest.json` is the per-step source of truth (`pipeline/manifest.py`).

**`STEP_ORDER`** (10 steps): `cv_extractor → tor_summarizer → checkpoint_1 → cv_tor_mapper →
checkpoint_2 → fields_generator → content_reviewer → compressor → checkpoint_3 → renderer`.

**Step status** ∈ `waiting | running | done | failed | blocked | pending | approved`. `update_step`
stamps `started_at` on the first transition to `running` and `completed_at` on terminal statuses.

**Derived signals** (pure helpers, surfaced on `GET /manifest`):
- `compute_progress(steps)` → 0–100 (done/approved = 1.0, in-flight = 0.5, per step).
- `current_running_step(steps)` → the running step, else the pending checkpoint, else `None`.

**Warnings** — `append_warning(run_dir, stage, kind, message, details)` appends to
`manifest.json["warnings"]`, **idempotently** (skips identical `stage/kind/message`). The orchestrator
backfills every agent's warnings into the manifest at its phase boundary, using readers in
`pipeline/validators.py`:

| After | Source → manifest stage |
|-------|--------------------------|
| Phase 1 | A1 `extraction_warnings` → `cv_extractor`; A2 soft-flags → `tor_summarizer` |
| Phase 2 | A3 `alignment.warnings` → `cv_tor_mapper` |
| Phase 3 | A4 `generation_warnings` + soft-flags → `fields_generator`; A5 review summary + soft-flags → `content_reviewer`; A6 soft-flags → `compressor` |

So warnings appear on the polled `/manifest` channel progressively as the run advances. See
`reference/api.md` and `frontend/progress-and-warnings.md`.

## Post-completion: the Field Editor (A7)

`POST /field-edit` (valid at `completed` or `checkpoint_3_pending`) calls `run_field_editor_task` **synchronously** inside
the HTTP handler (so the response carries applied/skipped), increments `sessions.round`, resets the
`checkpoint_3` + `renderer` manifest steps, and returns to `checkpoint_3_pending`. Approving
`checkpoint_3` re-runs Phase 4. See `reference/agents/a7-field-editor.md`.

## Hard block after A4

`validate_fields_generator_output` (`pipeline/validators.py`) halts Phase 3 with `set_failed` if A4
produced no usable `generated_fields` content — catching the silent "valid skeleton, empty content"
failure before A5/A6 run.

## Gotchas

- The content reviewer can set its manifest step to `blocked` (and `GET /manifest.reviewer_blocked`
  becomes `true`) while the pipeline still proceeds to `checkpoint_3_pending` — surface it as an
  advisory, not a hard stop.
- `run_phase4` skips (no upload, no `set_done`) if the `renderer` step is already `running` — guards
  against duplicate Phase 4 tasks.
