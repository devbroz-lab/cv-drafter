---
title: 0001 — Lean agent output contracts + parse-failure recovery
type: design
status: accepted
owner: backend
last_verified: 2026-06-09
code_refs:
  - pipeline/utils/llm.py
  - pipeline/config.py
  - pipeline/agents/cv_tor_mapper.py
  - pipeline/agents/fields_generator.py
  - pipeline/agents/content_reviewer.py
  - pipeline/agents/compressor.py
  - pipeline/utils/paths.py
related:
  - reference/agents/a3-cv-tor-mapper.md
  - reference/agents/a4-fields-generator.md
---

# 0001 — Lean agent output contracts + parse-failure recovery

## Context

A1 was switched from Sonnet 4.6 to Opus 4.8 for extraction quality. Opus produces richer, longer
`cv_data` (more projects, fuller text). A3 and A4 (and A5/A6) were "echo + augment" agents — their
prompts required reproducing the **entire** CVData verbatim and adding to it. So a larger A1 payload
inflated their output. Against the shared `ANTHROPIC_MAX_TOKENS = 32000` cap this produced two
failures: clean truncation (`stop_reason == max_tokens` → "pipeline failure") and, more insidiously,
malformed JSON on *completed* but oversized outputs (`Expecting ',' delimiter`), which the truncation
guard never caught. A1/A2 were unaffected because they never echo the big CVData.

## Decision

Keep Opus on A1. Make the downstream agents stop echoing the CVData, and add a recovery path:

- **Per-model token ceilings** (`config.py`): `ANTHROPIC_MAX_TOKENS = 64000` (Sonnet agents),
  `ANTHROPIC_MAX_TOKENS_EXTRACTOR = 64000` (Opus A1). Ceilings, not targets.
- **`call_agent_json`** (`pipeline/utils/llm.py`): centralised stream→parse with **intelligent**
  recovery — on JSON error or truncation it retries **only** when the agent supplies a `reduce_input`
  callback that shrinks the request (trims per-project free-text); with no callback it fails fast.
  Never re-sends the failing input.
- **Lean contracts:** A3 returns `alignment` only (Python reconstructs `data`); A4, A5, A6 return
  small **patches** (`generated_fields`/`project_overviews`; `review`; `compressed_fields`) that Python
  merges. A shared bracket/dot path setter (`pipeline/utils/paths.py`) applies the patches.
- **`MAX_PROJECTS_TO_KEEP` 30 → 15** to cut output volume (the floor stays 10).
- Donor-aware GIZ project narrative in A4 (the only project text GIZ renders).

## Consequences

**Good:** truncation and malformed-JSON failures eliminated; A3–A6 output is small regardless of input
richness; A5 lost its fragile "restore emptied fields" hack; one shared path utility.
**Bad/cost:** more Python merge logic; prompts must stay in sync with the merge code; the recovery
retry path is a safety net that, when it fires, sends less input (slightly degraded fidelity on that
rare run).

## Alternatives considered

- Revert A1 to Sonnet — rejected (loses extraction quality).
- Just raise `max_tokens` — insufficient (doesn't fix malformed JSON on completed outputs).
- Blind retry on parse failure — rejected (re-sends the same oversized input).
- Refactor A5/A6 the same way as A3/A4 was the chosen extension after the first runs showed the
  failure had simply moved to A5.

## Refs

Branch `fix/opus48-oversized-output-lean-agents`, commit `5c7bc6a`. Tests: `tests/test_llm_retry.py`,
`tests/test_paths.py`, `tests/test_cv_tor_mapper.py`, `tests/test_fields_generator_merge.py`,
`tests/test_content_reviewer_merge.py`, `tests/test_compressor_merge.py`.
