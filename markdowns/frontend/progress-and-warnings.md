---
title: Frontend — Pipeline Progress & Agent Warnings
type: frontend
status: current
owner: frontend
last_verified: 2026-06-09
code_refs:
  - api/routers/sessions.py
  - api/models/requests.py
related:
  - reference/api.md
  - reference/orchestration.md
  - design/0003-manifest-progress-warnings.md
---

# Frontend — Pipeline Progress & Agent Warnings

How the UI surfaces live progress and per-agent warnings. The backend is **poll-only** (React Query
`refetchInterval`, ~2.5s) — there is no push channel. Everything here is **additive**: the current UI
keeps working; adopt the new fields incrementally.

## What's new on `GET /manifest`

| Field | Type | Meaning |
|-------|------|---------|
| `progress` | `int` 0–100 | Accurate overall progress from step statuses (use instead of guessing from coarse status). |
| `current_step` | `string \| null` | The step in flight (running step, else the pending checkpoint). |
| `steps[].started_at` | `string \| null` (ISO) | When a step first ran — enables "running for Ns" / elapsed. |
| `warnings` | `WarningEntry[]` | All agent warnings so far, each tagged with its step (`stage`). |

## Polling

Poll `GET /status` (coarse) and `GET /manifest` (fine); stop when `status` is `completed` or `failed`.
`GET /manifest` returns **404** until the run starts (still `queued`) — keep the existing guard.

## `ManifestResponse` shape

```jsonc
{
  "session_id": "…",
  "db_status": "processing",
  "steps": [ { "name": "cv_extractor", "status": "done",
               "started_at": "…", "completed_at": "…" } ],
  "checkpoint_pending": "checkpoint_2",     // or null
  "reviewer_blocked": false,
  "progress": 68,                           // NEW
  "current_step": "fields_generator",       // NEW
  "warnings": [ { "stage": "cv_extractor", "kind": "extraction_warning",
                  "message": "…", "details": null } ]  // NEW
}
```

- **`progress`** = round(Σ step_weight / 10 × 100); done/approved = 1.0, in-flight
  (running/pending/blocked) = 0.5.
- **`started_at`** is stamped once and never overwritten; "running for X" = `now − started_at` while
  `completed_at` is null.

## Step model

**STEP_ORDER:** `cv_extractor, tor_summarizer, checkpoint_1, cv_tor_mapper, checkpoint_2,
fields_generator, content_reviewer, compressor, checkpoint_3, renderer`.
**Step status** ∈ `waiting | running | done | failed | blocked | pending | approved`.

Map backend steps to the existing recruiter-facing stages:

| Visual stage | Backend steps |
|---|---|
| Read inputs | `cv_extractor`, `tor_summarizer` |
| Match role | `checkpoint_1`, `cv_tor_mapper`, `checkpoint_2` |
| Write review | `fields_generator`, `content_reviewer` |
| Page limit | `compressor` |
| Final review | `checkpoint_3` |
| Generate doc | `renderer` |

## Warnings

`WarningEntry = { stage, kind, message, details? }`, where `stage` is the **step name** that produced
it, so you can group warnings under their step in the stepper. `manifest.warnings` is the **full
accumulated list each poll** (already de-duped server-side) — render it idempotently, don't append.

They arrive **progressively**:

| Available by | `stage` | `kind`(s) |
|---|---|---|
| `checkpoint_1_pending` | `cv_extractor` / `tor_summarizer` | `extraction_warning` / `scoring_keywords_empty`, `position_title_empty` |
| `checkpoint_2_pending` | `cv_tor_mapper` | `alignment_warning` |
| `checkpoint_3_pending` | `fields_generator` | `generation_warning`, `generation_warnings_high`, `partial_empty_generated_fields` |
| `checkpoint_3_pending` | `content_reviewer` | `review_findings`, `review_block_null`, `high_severity_count_unusual` |
| `checkpoint_3_pending` | `compressor` | `applied_false`, `target_not_reached`, `words_after_suspiciously_low` |

`review_findings.details = { high, low, passed }` — a compact badge. Full per-finding detail (with
`solvability`, `path`, `original`/`fixed`) is in `GET /review` / `GET /output`. Badge live, drill down
on demand.

Extraction failures also surface here: a CV that can't be read or yields no text fails Phase 1 with a
`cv_extractor` warning (`extraction_failed` / `no_extractable_text`) and a clear `error_message` on
`GET /status`.

## TypeScript types to add

```ts
export interface WarningEntry { stage: string; kind: string; message: string; details?: Record<string, unknown> | null; }
export interface ManifestStep { name: string; status: string; started_at: string | null; completed_at: string | null; }
export interface ManifestResponse {
  session_id: string; db_status: SessionStatus; steps: ManifestStep[];
  checkpoint_pending: string | null; reviewer_blocked: boolean;
  progress: number; current_step: string | null; warnings: WarningEntry[];
}
```

## Gotchas

- `manifest.warnings` is cumulative and de-duped — re-render from scratch each poll.
- A `content_reviewer` step can be `blocked` while the run still proceeds — advisory, not terminal.
- `field_editor_pending` is legacy; new runs don't enter it.
- `GET /warnings` exists for an on-demand full list; its `stage`/`counts` keys are now step names. The
  UI generally doesn't need it — `manifest.warnings` already streams everything.

See `reference/api.md` for the full endpoint surface and `reference/orchestration.md` for how status
and the manifest are driven.
