---
title: A1 — CV Extractor
type: reference
status: current
owner: backend
last_verified: 2026-06-08
code_refs:
  - pipeline/agents/cv_extractor.py
  - pipeline/utils/cefr.py
  - pipeline/utils/llm.py
  - models.py
related:
  - reference/extraction.md
  - reference/data-model.md
  - reference/artifacts.md
---

# A1 — CV Extractor

Reads the tagged CV plain text and produces a structured `CVData`. First agent; runs in parallel with
A2 during Phase 1.

- **Model:** Opus (`ANTHROPIC_MODEL_EXTRACTOR`) — the strongest model, for extraction fidelity.
- **Input:** `<donor>` + `<cv>` tagged text (from `pipeline.extractor`).
- **Output:** `cv_data.json` → `{approved, approved_at, data: CVData}`.
- **Manifest step:** `cv_extractor`.

## What the prompt does (highlights — see `SYSTEM_PROMPT_A1`)

JSON-only output, strict extraction (no invention). Notable rules:
- **Format-specific experience routing.** GIZ: all work → `relevant_projects`, `employment_record`
  empty. WB: populate both `employment_record` and `relevant_projects`.
- **Project description split.** `main_project_features` = project context; `activities_performed` =
  the candidate's actions.
- **Employment-only fallback.** If `relevant_projects` is empty but `employment_record` exists, map
  each employment entry to a project (`description → main_project_features`).
- Merged-cell/two-column project tables, date-ordering validation (swap inverted ranges),
  placeholder detection, label-driven `other_skills`/`certifications`/`training` routing,
  certifications dual-routing, references-vs-publications routing, certification declaration.
- Leaves `proposed_position`/`category`/`employer`/`years_with_firm`/`generated_fields` empty
  (injected/filled later).

## Python post-processing (`cv_extractor.run`)

1. Injects the session params (`proposed_position`, etc.) into the validated `CVData`.
2. `_populate_cefr_fields` — maps `*_raw` language levels to `*_cefr` via `pipeline/utils/cefr.py`,
   respecting `language_scale_direction` (numeric 1=best vs 1=worst).
3. `_apply_employment_fallback` — Python safety net mirroring the prompt's fallback (idempotent).

## Contracts & invariants

- The LLM call goes through `call_agent_json` (`pipeline/utils/llm.py`) with **no `reduce_input`** —
  A1 must extract its raw text faithfully, so a parse failure fails fast (no retry).
- Output is validated against `CVData` before writing; a `max_tokens` truncation or schema-invalid
  result raises and fails the step.

## Gotchas

- A1's richness drives downstream output size; this is why A3–A6 use lean (non-echo) contracts (see
  `design/0001-lean-agent-output-contracts.md`).
- `extraction_warnings` it emits are backfilled onto the manifest in Phase 1
  (`reference/orchestration.md`).
