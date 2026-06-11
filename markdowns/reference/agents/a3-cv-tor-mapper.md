---
title: A3 — CV–ToR Mapper
type: reference
status: current
owner: backend
last_verified: 2026-06-09
code_refs:
  - pipeline/agents/cv_tor_mapper.py
  - pipeline/precompute_utils.py
  - pipeline/utils/llm.py
related:
  - reference/artifacts.md
  - reference/data-model.md
  - design/0001-lean-agent-output-contracts.md
---

# A3 — CV–ToR Mapper

Scores each project for relevance to the ToR and selects which to keep. Phase 2.

- **Model:** Sonnet (`ANTHROPIC_MODEL`).
- **Input:** `cv_data.json` + `tor_data.json` + `manifest.params`.
- **Output:** `mapped_cv.json` → `{approved, approved_at, data: CVData, alignment}`.
- **Manifest step:** `cv_tor_mapper`.

## Python pre-compute (before the LLM)

- `_precompute_project_dates_for_mapper` — fills each project's `duration`/`year` (so A3 can use
  duration as a scoring signal, and so A4 downstream doesn't recompute).
- `_precompute_relevance_scores` — Python computes 50% of relevance per project: keyword overlap
  (35%, from merged `scoring_keywords`) + geography (15%, from `country_experience_required`),
  combined into a `composite_score` injected as `<pre_computed>`. The LLM adjusts ±0.10 for the
  semantic dimensions (tasks 30% + competencies 20%).

## Output contract — `alignment` only (no data echo)

A3 returns **only** the `alignment` object (`kept_sections`, `dropped_sections`,
`project_scores[{project_name, relevance_score, matched_*, kept}]`, `warnings`). It does **not**
reproduce the CVData. The pipeline reconstructs `data` deterministically from the input CV; this keeps
A3's output small regardless of how rich the Opus-extracted input is (see
`design/0001-lean-agent-output-contracts.md`).

## Python post-processing (after the LLM)

On the reconstructed `data`, in order:
1. `_enforce_threshold_and_cap` — drop projects below the dynamic threshold (`0.30`/`0.40`/`0.50` by
   count), restore top-scoring to meet the floor (`MIN_PROJECTS_TO_KEEP = 10`), cap at
   `MAX_PROJECTS_TO_KEEP = 15`. Warnings recorded in `alignment.warnings`.
2. `_protect_current_role` — unconditionally restore the most-recent ongoing ("Present") project if it
   was dropped (human editors always keep the current role).
3. `_sort_by_date_desc(relevant_projects)` — newest-first by `date_from` (so A4 generates content in
   render order; preserves WB positional pairing).
4. `collapse_by_date_range` + `_sort_by_date_desc(countries_of_experience, primary_key="date_to")`.

`project_scores` in `alignment` keeps **all** scored projects (kept and dropped); only
`data.relevant_projects` is filtered.

## Contracts & invariants

- LLM call via `call_agent_json` with a `reduce_input` that trims per-project free-text on a
  parse/truncation failure (recovery only).
- Every project from the input must appear in `project_scores`, keyed by exact `project_name` (the
  reconstruction matches on it).
