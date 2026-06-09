---
title: A5 — Content Reviewer
type: reference
status: current
owner: backend
last_verified: 2026-06-09
code_refs:
  - pipeline/agents/content_reviewer.py
  - pipeline/validation.py
  - pipeline/utils/paths.py
  - pipeline/utils/llm.py
related:
  - reference/data-model.md
  - design/0001-lean-agent-output-contracts.md
---

# A5 — Content Reviewer

Reviews the generated CVData for factual/style issues, flags high-severity problems, and auto-fixes
low-severity ones. **Non-blocking** — the pipeline continues regardless. Phase 3.

- **Model:** Sonnet (`ANTHROPIC_MODEL`).
- **Input:** `generated_fields.json["generated"]` + `tor_data.json` + a `<pre_computed>` context.
- **Output:** updates `generated_fields.json` in place — writes the `review` block and the
  (low-severity-fixed) `generated`.
- **Manifest step:** `content_reviewer` (may be set `blocked` when `passed=false`).

## Output contract — `review` only (no CVData echo)

A5 returns **only** the `review` block:
```
review: { high_severity:[{path, field, issue, recommendation, solvability}],
          low_severity:[{path, field, issue, original, fixed, solvability}],
          passed }
```
`content_reviewer.run` applies each low-severity `fixed` to its `path` on a copy of the generated data
via the shared setter (`pipeline/utils/paths.set_by_path`; best-effort — unresolved paths are
skipped). high-severity entries are flag-only and change nothing. This removes the old full-data echo
and the "restore emptied fields" hack (see `design/0001-lean-agent-output-contracts.md`).

## Solvability

Every finding carries `solvability` ∈ `"pipeline"` (A7 field-editor can fix it via a scalar rewrite)
or `"human"` (needs recruiter judgement / external info). Drives the UI's call-to-action.

## Pre-computed context (`_precompute_context`)

Deterministic facts injected for the LLM (it must not recompute them): `tier`,
`required_experience_years`, `documented_total_years`, `documented_energy_years`,
`experience_gap_years`, and a `geographic_alternative` summary (`pipeline/validation.py`).

## Python post-processing (`_apply_post_processing`)

- `_inject_experience_gap_finding` — for `team_lead` tier with an energy-sector gap ≥ threshold,
  injects a standardised high-severity finding (`solvability: "human"`).
- `_filter_word_count_pedantry` — drops low-severity word-count flags within tolerance.
- `_enforce_passed_field` — forces `passed=false` whenever `high_severity` is non-empty.

## Contracts & invariants

- LLM call via `call_agent_json` with a `reduce_input` (trims project text on failure).
- Style/quality checks are scoped to `generated_fields[*].content`; source-extracted fields are
  out of scope for style review (factual checks still apply).
- Non-blocking: `run_phase3` logs and continues to A6 even when `passed=false`. A
  `review_findings` summary is backfilled onto the manifest; full detail is in `GET /review`.
