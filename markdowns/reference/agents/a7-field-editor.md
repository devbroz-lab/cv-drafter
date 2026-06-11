---
title: A7 — Field Editor
type: reference
status: current
owner: backend
last_verified: 2026-06-09
code_refs:
  - pipeline/agents/field_editor.py
  - pipeline/orchestrator.py
  - pipeline/utils/paths.py
related:
  - reference/orchestration.md
  - reference/renderer.md
  - reference/api.md
---

# A7 — Field Editor

Applies targeted, user-directed natural-language edits to specific fields **after** the document is
complete. Out of band — not part of Phases 1–4 and **has no manifest step**.

- **Model:** Sonnet (`ANTHROPIC_MODEL`), called once per edit (non-streaming `messages.create`).
- **Trigger:** `POST /sessions/{id}/field-edit` (valid at `completed` or `checkpoint_3_pending` —
  the latter lets the user resubmit edits skipped on a prior call without a full re-render).
- **Output:** mutates `generated_fields.json["generated"]` in place (preserves all other keys).

## Flow

`POST /field-edit` → `increment_round` → `set_processing` → `run_field_editor_task`
(**synchronous**, so the HTTP response carries `applied`/`skipped`/`kq_source`) →
resets the `checkpoint_3` (pending) and `renderer` (waiting) manifest steps →
`set_checkpoint_pending(3)`. Approving checkpoint 3 re-runs Phase 4, producing
`round_{NN}_{donor}.docx`. See `reference/orchestration.md`.

## Per-edit resolution (`run_field_editor`, up to 5 edits)

For each `{field_path, instruction}`:
1. **Paragraph-placeholder resolution** — a `paragraph_N` fallback path from the viewer is matched (by
   fuzzy text) to a `key_qualifications[i]` / `generated_fields[j].content` / `other_relevant_info`
   path.
2. **Renderer-field check (`RENDERER_FIELD_MAP`)** — edits to fields not rendered for the donor are
   redirected to the nearest rendered field (GIZ `activities_performed → main_project_features`) or
   skipped with a reason.
3. **CEFR enrichment** — for an empty GIZ `*_cefr`, the displayed (mapped from `*_raw`) value is shown
   to the model so it edits from what the user saw.
4. **Apply** — Claude returns `{"action":"apply","value"}` or `{"action":"skip","reason"}`; on apply,
   the new scalar is written via `pipeline/utils/paths.set_by_path`. Non-scalar targets, unresolved
   paths, unchanged values, and API errors all become `skipped` entries (reasons capped at 200 chars).

## Response

`FieldEditResponse` — `applied[]`, `skipped[]`, `round`, `status: "checkpoint_3_pending"`, and
`kq_source` ∈ `"ai_generated" | "extracted" | "absent"` (which source feeds the key-qualification
bullets the edits target). The agent is authoritative about recruiter-supplied facts — it defaults to
"apply" and only skips when an instruction asks to add a specific named credential it can't ground.

## Contracts & invariants

- The path resolver/setter is the **shared** `pipeline/utils/paths` module (same one A5/A6 use).
- A7 never re-runs A4/A5/A6 — it edits the existing `generated` data directly, then the document is
  re-rendered.
