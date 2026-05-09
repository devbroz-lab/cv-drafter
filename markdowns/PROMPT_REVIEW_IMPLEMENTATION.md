# Prompt Review Implementation Summary

**Status**: All P-corrections implemented (P2–P19), except P2-A3 relevance scoring (deferred with stub).

**Date**: 2026-05-09

**Source**: `additions/PROMPT_REVIEW_CONTEXT.md` — comprehensive findings + correction plan from full 7-agent review.

---

## What changed

### New files

| File | Purpose |
|---|---|
| `pipeline/precompute_utils.py` | Shared deterministic helpers: word counting, date/duration calculation, protected-field restoration. Replaces LLM arithmetic with Python. |
| `additions/RELEVANCE_SCORING_DESIGN.md` | Deferred design notes for P2-A3 (Python relevance scoring for Agent 3). |
| `tests/test_precompute_utils.py` | 32 tests for shared utilities |
| `tests/test_fields_generator_precompute.py` | 9 tests for A4 date pre-fill |
| `tests/test_compressor_postprocessing.py` | 13 tests for CompressionResult model + A6 post-processing |
| `tests/test_field_editor_context.py` | 23 tests for A7 context enrichment (P5) |

**Test coverage**: 77/77 tests passing (includes 3 pre-existing).

---

### Modified files (by phase)

#### Phase 0: Foundation
- **`pipeline/precompute_utils.py`** (new) — Shared utilities for all agents

#### Phase 1: Agent 1 (CV Extractor)
- **`pipeline/agents/cv_extractor.py`**
  - **P11**: Typo-correction rule narrowed — never touch proper nouns, names, institutions, countries, acronyms. Only common-word typos (`teh`→`the`).
  - **P12**: `present_position` tie-breaker explicitly defined (4-step priority: Present entries → latest date_from → latest date_to → document order).

#### Phase 2: Agent 2 (ToR Summarizer)
- **`pipeline/agents/tor_summarizer.py`**
  - **P6 supplementary (Option A)**: Added extraction rule for `DistilledToR.geography` field (short human-readable string, e.g. "South Africa").

#### Phase 3: Agent 3 (CV-ToR Mapper)
- **`pipeline/agents/cv_tor_mapper.py`**
  - **P6 (Option B)**: Geography scoring dimension now uses `country_experience_required` (list) instead of `geography` (flat string).
  - **P13**: Fallback rule added: "If `min_projects_to_keep` not in params, default to 2."
  - **P2-A3 (deferred)**: `_precompute_relevance_scores()` stub returns `None`; conditional `<pre_computed>` block hook in place. TODO marker + design doc added.

#### Phase 4: Agent 4 (Fields Generator)
- **`pipeline/agents/fields_generator.py`**
  - **P14**: Minimum-bullet rule softened — "Aim for 3–6, but minimum is 1 strong bullet if ToR has fewer than 3 clusters."
  - **P15**: `_precompute_project_dates()` pre-fills `duration` and `year` per project using `precompute_utils` before LLM call. Prompt updated: "Copy as received — do not recalculate."

#### Phase 5: Agent 5 (Content Reviewer)
- **`pipeline/agents/content_reviewer.py`**
  - **P3**: Added `## Pre-computed context` section to prompt explaining each `<pre_computed>` field (tier, experience gap, geographic alternative) and how to use them. Experience gap: "Acknowledge but do not re-flag — Python injects the finding."
  - **P4**: Added auto-fix note: "Fixes applied once, not re-reviewed. Prefer minimal rewrites."

#### Phase 6: Agent 6 (Compressor)
- **`models.py`**
  - **New models**: `FieldShortened` and `CompressionResult` (Pydantic) replacing raw dict with asserts.
  - `CompressionResult` includes new fields: `target_not_reached` (P18), `protected_field_restorations` (P17 audit).
- **`pipeline/agents/compressor.py`**
  - **P16**: Pre-compute `words_before` and `words_per_field` in Python; pass into `<compression_params>`. Post-compute: authoritative `words_after` from Python, overwriting LLM estimate.
  - **P17**: Prompt no longer says "character for character." Post-processing: `restore_protected_fields()` deterministically restores any inadvertently altered protected field; audit in `protected_field_restorations` list.
  - **P18**: Prompt instructs: "If target unreachable without violating rules, set `target_not_reached=true`." Output shape updated.
  - **P19**: `generation_warnings` read from file, passed into `<generation_warnings>` block, copied unchanged into output. Prompt documents passthrough.
  - **Validation**: `CompressionResult.model_validate()` replaces raw dict asserts.

#### Phase 7: Agent 7 (Field Editor)
- **`pipeline/agents/field_editor.py`**
  - **P5 context enrichment**:
    - New constant: `FIELD_WORD_LIMITS` dict keyed by `(donor, field_key)` — GIZ key_qualifications=25, WB detailed_tasks=30.
    - `_field_key_from_path()` helper extracts logical field key from bracket/dot path.
    - `build_user_prompt()` now includes: `Field key`, `Donor format`, `Word limit`, `CV context` (proposed position + top 2–3 project names).
    - `SYSTEM_PROMPT_A7` updated to reference and respect new context sections.
    - `call_claude()`, `run_field_editor()`, `run()` all accept `donor` and `cv_context` kwargs.
- **`pipeline/orchestrator.py`**
  - New helper: `_build_field_editor_context()` builds donor + cv_context from session row + `generated_fields.json`.
  - `run_field_editor_task()` calls helper and passes context down to `field_editor.run()`.

#### Phase 8: Documentation
- **`additions/PROMPT_REVIEW_CONTEXT.md`**
  - §5: Added implementation status table (all P-items marked resolved or deferred).
  - §3: Updated `geography` field note — now populated by A2.
  - §7: Updated quick-reference table with new owners (duration/year → A4 pre-compute; words_before → A6 pre-compute; words_after → A6 post-compute; protected-field restore → A6 post-compute).
- **`additions/RELEVANCE_SCORING_DESIGN.md`** (new) — Deferred P2-A3 design.
- **`markdowns/AGENT_INPUT_TEMPLATE_CONTEXT.md`** — Updated tag-block matrix + examples.
- **`markdowns/PIPELINE_CONTEXT.md`** — Added `precompute_utils.py` row; updated field_editor task note.
- **`markdowns/RUNS_ARTIFACTS_CONTEXT.md`** — Updated `generated_fields.json` + agent quick-lookup table.

---

## Impact summary

| Correction | Scope | Benefit |
|---|---|---|
| **P2/P15/P16** (LLM arithmetic → Python) | A4, A6 | Reliable date/duration/word-count calculations; no more hallucinated durations or off-by-10 word counts. |
| **P3** (A5 pre-computed context) | A5 prompt | LLM now knows how to use experience gap, tier, geographic alternative — fewer redundant/contradictory findings. |
| **P4** (A5 auto-fix note) | A5 prompt | Conservative fixes — fewer scope-creep rewrites. |
| **P5** (A7 context enrichment) | A7 + orchestrator | Field editor sees word limits, donor conventions, CV grounding — better quality post-completion edits. |
| **P6** (geography field + scoring fix) | A2, A3 | Geography now populated + scored correctly; no more empty-string score dimension. |
| **P11/P12** (A1 typo/present_position rules) | A1 prompt | Safer typo correction; deterministic present_position fallback. |
| **P13** (A3 min_projects fallback) | A3 prompt | Explicit default when param missing (defensive). |
| **P14** (A4 min bullets softened) | A4 prompt | No more padding with weak bullets when ToR has <3 clusters. |
| **P17** (A6 protected-field restore) | A6 post-processing | Deterministic restore if LLM touches personal_info/education/etc. |
| **P18** (A6 target_not_reached flag) | A6 prompt + model | Pipeline surfaced when compression can't reach target — human review signal. |
| **P19** (A6 generation_warnings passthrough) | A6 | Warnings from A4 no longer lost; surfaced in final output. |
| **P2-A3** (relevance scoring) | A3 stub | Deferred — design documented, hook in place for future implementation. |

---

## Backward compatibility

- **Schema additions only**: `CompressionResult` is new; all other schema changes are additive (new optional fields).
- **Field editor signature extended**: `donor` and `cv_context` are optional kwargs — old callers still work (backward-compatible).
- **A3 `<pre_computed>` conditional**: Only emitted when stub returns non-None — no behaviour change today.
- **Protected-field restoration**: Defensive post-processing; no-op in normal operation (audit list empty).
- **Existing tests pass**: 3 pre-existing tests + 74 new tests = 77/77 passing.

---

## Follow-up work

1. **P2-A3 relevance scoring**: Implement keyword-overlap + geography-overlap scoring in Python (see `RELEVANCE_SCORING_DESIGN.md`). Requires:
   - Tokenisation / bag-of-words keyword matching.
   - Optional: embedding API for semantic task/competency matching.
   - Regression testing against existing sessions.

2. **Compression ratio plumbing**: `FormatProfile.default_compression_ratio` is declared but never read — both renderers hardcode `0.80`. Either wire it or remove the dead schema field.

3. **Live-API smoke tests**: Current tests use mocks/fixtures. Run a full GIZ + WB session end-to-end with real LLM calls to verify prompt changes don't regress quality.

4. **`geography` vs `country_experience_required` reconciliation**: Consider deprecating `geography` string field entirely if `country_experience_required` list proves sufficient. Currently both exist (P6 Option B + A).

---

## File manifest (full list of touched files)

### Created (6)
- `pipeline/precompute_utils.py`
- `additions/RELEVANCE_SCORING_DESIGN.md`
- `tests/test_precompute_utils.py`
- `tests/test_fields_generator_precompute.py`
- `tests/test_compressor_postprocessing.py`
- `tests/test_field_editor_context.py`

### Modified (10)
- `pipeline/agents/cv_extractor.py`
- `pipeline/agents/tor_summarizer.py`
- `pipeline/agents/cv_tor_mapper.py`
- `pipeline/agents/fields_generator.py`
- `pipeline/agents/content_reviewer.py`
- `pipeline/agents/compressor.py`
- `pipeline/agents/field_editor.py`
- `pipeline/orchestrator.py`
- `models.py`
- `additions/PROMPT_REVIEW_CONTEXT.md`

### Documentation updated (4)
- `markdowns/AGENT_INPUT_TEMPLATE_CONTEXT.md`
- `markdowns/PIPELINE_CONTEXT.md`
- `markdowns/RUNS_ARTIFACTS_CONTEXT.md`
- `markdowns/PROMPT_REVIEW_IMPLEMENTATION.md` (this file)

**Total**: 20 files touched, 77/77 tests passing.
