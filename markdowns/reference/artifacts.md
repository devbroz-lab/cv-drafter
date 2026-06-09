---
title: Run-Directory Artifacts
type: reference
status: current
owner: backend
last_verified: 2026-06-08
code_refs:
  - pipeline/manifest.py
  - pipeline/artifacts.py
  - pipeline/agents/cv_extractor.py
  - pipeline/agents/cv_tor_mapper.py
  - pipeline/agents/fields_generator.py
related:
  - reference/data-model.md
  - reference/orchestration.md
---

# Run-Directory Artifacts

Each session has a directory `runs/{session_id}/` (`pipeline/paths.RUNS_ROOT`, path-traversal-guarded
by `validate_run_id`). The JSON files there are the contracts between agents.

## Dependency graph

```
manifest.json   (created Phase 1; updated every step)
cv_data.json  ─┐
               ├─▶ mapped_cv.json ─▶ generated_fields.json ─▶ output.docx
tor_data.json ─┘
```

## File-by-file

### `manifest.json`
Operational, not a CV schema. Keys: `params` (the pipeline params dict), `steps[]`
(`{name, status, started_at, completed_at}`), and `warnings[]` (`{stage, kind, message, details}`).
Produced by `create_manifest`; mutated by `update_step` / `append_warning`. Read by agents that need
`params` and by `GET /manifest` + `GET /warnings`. See `reference/orchestration.md`.

### `cv_data.json` — A1 output
Envelope `{approved, approved_at, data: CVData}`. `data` is the faithfully-extracted candidate
(`reference/data-model.md`), with CEFR fields populated deterministically and an employment-fallback
applied when needed. Consumed by A3.

### `tor_data.json` — A2 output
Envelope `{approved, approved_at, pools: [DistilledToR, …], selected_pool_index}`. A2 may emit
multiple expert-role pools; the UI prunes to the chosen one at checkpoint 1
(`POST /tor/select-pool` → one pool, index 0). Downstream agents resolve the ToR via
`resolve_tor_for_agents` / `resolve_selected_tor_pool` (`pipeline/utils/_helpers.py`). Consumed by
A3, A4, A5, A6.

### `mapped_cv.json` — A3 output
Envelope adds `approved`/`approved_at`. `data` → `CVData` with `relevant_projects` filtered/capped to
the kept set and sorted newest-first; `countries_of_experience` collapsed by date range. `alignment`
→ the scoring report (`project_scores` for **all** scored projects, `warnings` for Python enforcement
actions). Consumed by A4.

### `generated_fields.json` — A4/A5/A6 (and A7) output
The evolving late-pipeline envelope:
- `generated` → `CVData` (derived fields filled, `generated_fields` populated, reviewed, compressed).
- `generation_warnings` → list from A4, passed through by A5/A6.
- `review` → A5's block (`high_severity[]`, `low_severity[]`, `passed`; each finding has
  `solvability`).
- `compression` → A6's `CompressionResult`.
Written initially by A4; updated **in place** by A5, A6, and (post-completion) A7. Read by the
renderers (`generated`) and by `GET /output` / `GET /review`.

## Same entity, three roles

`CVData` appears in `cv_data.json` (extracted), `mapped_cv.json` (filtered), and
`generated_fields.json` (generated/reviewed/compressed). One Pydantic type, three lifecycle stages —
see `reference/data-model.md`.

## Approval stamping

At each checkpoint, `pipeline/artifacts.stamp_approved` sets `approved: true` / `approved_at` on the
relevant artifact. These are **audit metadata only** — orchestration keys off DB status and manifest
steps, not the stamp.

## Non-JSON artifacts

`input/` (Phase 1 temp source, deleted in `finally`), the per-format dynamic template + unpacked dir
(`reference/renderer.md`), and the final `output.docx`.
