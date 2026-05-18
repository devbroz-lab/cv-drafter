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

---

## Round 2 — Pipeline Diagnostic Fixes (May 2026)

Implements fixes identified in `additions/PIPELINE_DIAGNOSTIC_CONTEXT.md`.

### Model centralisation + Fix 1 (Agent 4 → Sonnet)

All pipeline agents now import their model string from `pipeline/config.py` rather than hardcoding it at the call site.  Two constants are defined:

- `ANTHROPIC_MODEL` — Haiku; default for A1, A2, A3, A5, A6.
- `ANTHROPIC_SYNTHESIS_MODEL` — Sonnet; used exclusively by A4 (`fields_generator`).  This is Fix 1: A4 is the sole generative synthesis agent and requires Sonnet-class reasoning to produce ToR-grounded qualification bullets across four simultaneous input blocks.

Affected agents: `cv_extractor.py`, `tor_summarizer.py`, `cv_tor_mapper.py`, `fields_generator.py`, `compressor.py`.  `content_reviewer.py` already imported `ANTHROPIC_MODEL`; no change.  `field_editor.py` retains its own module-level `MODEL` constant (Dev 2's independent decision).

### Fix 5a — Hard-block validator after Agent 4

New `pipeline/validators.py` introduces `PipelineValidationError` and `validate_fields_generator_output`.  The validator reads `generated_fields.json` after A4 and raises if every `generated_fields[i].content` is empty (all-or-nothing rule matching the observed silent failure mode).

Wired in `orchestrator.run_phase3` between the `fields_generator.run` call and `content_reviewer.run`.  On failure: `fields_generator` manifest step is overridden from `done` to `failed`; `set_failed(session_id, message)` is called; A5 and A6 do not run.

### Fix 3 — CEFR centralised at Agent 1 write time

`_populate_cefr_fields(parsed: CVData)` added to `pipeline/agents/cv_extractor.py`.  Called after LLM response parsing and param injection, before `cv_data.json` is written.  Maps `*_raw` → `*_cefr` for every language entry whose structured field is empty, using `pipeline.utils.cefr.map_cefr`.  Idempotent — never overwrites an already-populated value.

Downstream effects:
- `templates/giz.py → _resolve_cefr` fallback remains structurally correct; it now exercises only for sessions pre-dating this fix or genuinely empty raw values.
- `field_editor.py` CEFR enrichment block (Fix 3 from Round 1) remains as a defensive fallback; becomes a no-op in normal operation.
- Agent 1 system prompt unchanged — the LLM correctly leaves `*_cefr` fields empty; Python populates them.

### Fix 6 — Agent 7 routing decision surfaced via API

`kq_source_label(generated: dict) -> str` added to `field_editor.py` as a public helper.  Translates `_key_qualification_source`'s internal return to API-facing labels:

| Internal | API label | Meaning |
|----------|-----------|---------|
| `"generated_fields"` | `"ai_generated"` | A4's ToR-tailored content is active |
| `"raw"` | `"extracted"` | A1's raw extraction is active (A4 produced no usable content) |
| `"none"` | `"absent"` | Neither source has bullets |

The outer `field_editor.run()` now returns `(applied, skipped, kq_source)` — third value computed from the post-edit state of `mutated`.  `orchestrator.run_field_editor_task` threads it through.  `FieldEditResponse` gains a required `kq_source: Literal["ai_generated", "extracted", "absent"]` field.  The router destructures all three values and passes `kq_source` into the response.

The label reflects the post-edit state so a successful edit that promotes the source (e.g. a write to `generated_fields[j].content` that populates a previously absent entry) is reflected accurately.

### New files (3)

- `pipeline/validators.py`
- `tests/test_validators.py`
- `tests/test_cv_extractor_cefr.py`

### Modified files (11)

- `pipeline/config.py`
- `pipeline/agents/cv_extractor.py`
- `pipeline/agents/tor_summarizer.py`
- `pipeline/agents/cv_tor_mapper.py`
- `pipeline/agents/fields_generator.py`
- `pipeline/agents/compressor.py`
- `pipeline/agents/field_editor.py`
- `pipeline/orchestrator.py`
- `api/models/requests.py`
- `api/routers/sessions.py`
- `tests/test_field_editor_context.py`
- `tests/test_field_editor_skip_reasons.py` (pre-existing `_base_kwargs` updated for new required field)

### Documentation updated (5)

- `markdowns/PIPELINE_CONTEXT.md`
- `markdowns/PROMPT_REVIEW_CONTEXT.md`
- `markdowns/PROMPT_REVIEW_IMPLEMENTATION.md` (this file)
- `markdowns/RUNS_ARTIFACTS_CONTEXT.md`
- `markdowns/API.md`
- `markdowns/FRONTEND_SKIP_REASONS_CONTEXT.md`

**Total Round 2**: 14 files touched, 168/168 tests passing.

---

## Round 3 — Diagnostic Fixes Round 2 (May 2026)

Implements Fixes 7, 8 (Parts 1/2/3), 9, and Fix J from `additions/PIPELINE_DIAGNOSTIC_CONTEXT.md`.

### Fix 9 — `FieldShortened.subfield` optional

`models.py:515` — `subfield: str | None = Field(default=None, ...)`.  Agent 6 emits
`null` for dot-path field entries and bracket-index strings for list entries — both now
deserialise cleanly.  Backward-compatible with existing `""` values on disk.

### Fix 7 — `map_cefr` normalisation

`pipeline/utils/cefr.py` — added `CEFR_UNRESOLVABLE_SENTINEL = "?"`, regex
`_PAREN_PATTERN`, `_NUMERIC_PATTERN`, and a rewritten `map_cefr` that handles
parenthetical formats (`"Proficient (C2)"` → `"C2"`) and numeric scale inputs
(`"1"`, `"3/5"` → `"?"`).  Propagates automatically to `cv_extractor.py`,
`templates/giz.py`, and `field_editor.py` — no call-site changes.

### Fix J + Fix 8 Part 1 — Python threshold enforcement + project cap

`pipeline/agents/cv_tor_mapper.py`:
- `MAX_PROJECTS_TO_KEEP = 6` constant alongside existing `MIN_PROJECTS_TO_KEEP = 2`.
- `_compute_threshold(total)` mirrors the prompt's dynamic threshold rule.
- `_enforce_threshold_and_cap(parsed, original_projects)` runs in-place after LLM
  parse, before `CVData.model_validate`. Applies threshold enforcement, minimum
  guarantee restoration, and cap truncation in sequence. Preserves original CV
  document order when rebuilding `data.relevant_projects`. Appends warning strings
  to `alignment.warnings` for each action taken.

### Fix 8 Part 3 — Per-project text cap

`pipeline/agents/fields_generator.py`:
- `A4_INPUT_PROJECT_WORD_CAP = 150` constant.
- `_truncate_project_text_for_a4(cv_data)` deep-copies `cv_data` and trims
  `activities_performed` and `main_project_features` per project to the cap with
  a `"…"` suffix. Called between `_precompute_project_dates` and user message
  assembly. `mapped_cv.json` on disk is not affected.
- `import copy` moved to module-level (was inside `_precompute_project_dates`).

### Fix 8 Part 2 — A4 prompt priority + minimum output guarantee

`SYSTEM_PROMPT_A4` in `pipeline/agents/fields_generator.py`:
- New `## OUTPUT PRIORITY ORDER` section after the intro paragraph: generate
  `generated_fields` first, fill derived fields second, ensure Part 2 is complete
  under output-length pressure.
- New `### Minimum output guarantee` subsection in Part 2: at least one non-empty
  `GeneratedField` per `generative_field_keys` key even when alignment is weak;
  never return empty `content`; flag low-confidence entries in `generation_warnings`.
- Minimum-1 language added inline to both GIZ and WB "how many" subsections.

### New files (5)

- `tests/test_cefr_map.py` — 53 tests
- `tests/test_cv_tor_mapper.py` — 23 tests
- `tests/test_fields_generator_text_cap.py` — 16 tests
- `tests/test_fields_generator_prompt.py` — 9 tests
- (integration tests in existing `tests/test_cv_extractor_cefr.py` — 2 new)

### Modified files (4)

- `models.py`
- `pipeline/utils/cefr.py`
- `pipeline/agents/cv_tor_mapper.py`
- `pipeline/agents/fields_generator.py`
- `tests/test_compressor_postprocessing.py` (6 new tests in `TestFieldShortenedOptionalSubfield`)

### Documentation updated (5)

- `additions/PIPELINE_DIAGNOSTIC_CONTEXT.md` — Round 2 record, merged duplicate Issue K, all Round 2 fixes marked implemented.
- `markdowns/PROMPT_REVIEW_CONTEXT.md` — `extraction_warnings` corrected; implementation status rows added; §7 quickref extended.
- `markdowns/PROMPT_REVIEW_IMPLEMENTATION.md` (this file) — Round 3 section.
- `markdowns/PIPELINE_CONTEXT.md` — `cv_tor_mapper` and `fields_generator` rows updated.
- `markdowns/RUNS_ARTIFACTS_CONTEXT.md` — `mapped_cv.json` row updated.

**Total Round 3**: 10 files touched, 277/277 tests passing (109 new tests).

---

## Round 4 — Diagnostic Fixes Round 3 (May 2026)

Implements Fix M (Parts 1 and 2) from `additions/PIPELINE_DIAGNOSTIC_CONTEXT.md`.

### Fix M Part 1 — Numeric 1–5 CEFR scale mapping

`pipeline/utils/cefr.py` — complete rewrite of the numeric-scale handling path:
- `NUMERIC_SCALE_TO_CEFR` public constant: `"1"→"C1"`, `"2"→"B2"`, `"3"→"B1"`, `"4"→"A2"`, `"5"→"A1"`.
- Private `_try_numeric_scale(token)` helper.
- Private `_map_numeric_or_sentinel(raw)` handles bare integers (1–5 → mapped; outside → `"?"`), slash-separated all-integer strings (all in-range → joined mapped labels; any out-of-range → `"?"`), and non-numeric inputs (returns `None`).
- `_BARE_INT_PATTERN` and `_SLASH_NUMERIC_PATTERN` regexes.
- `map_cefr` step 2 (parenthetical) now also applies numeric-scale mapping on inner text (`"Level (3)"` → `"B1"`).
- `map_cefr` step 3 delegates to `_map_numeric_or_sentinel`.
- Module docstring updated to document the full resolution order.

`"?"` sentinel is now reserved exclusively for genuinely unresolvable inputs (integers outside 1–5, slash strings with any out-of-range digit). Propagates automatically to `cv_extractor._populate_cefr_fields`, `templates/giz.py:_resolve_cefr`, and `field_editor.py`'s CEFR enrichment block — no call-site changes.

### Fix M Part 2 — A4 truncation-text restoration

`pipeline/agents/fields_generator.py`:
- `import logging` + module-level `log = logging.getLogger(__name__)`.
- `_restore_truncated_project_text(cv_data_out, original_cv_data) -> dict` helper: deep-copies `cv_data_out`, restores `activities_performed` and `main_project_features` from `original_cv_data` by project index (unconditionally). Logs a warning and skips if project counts differ.
- In `run()`: `cv_data_full = cv_data` assigned after `_precompute_project_dates` and before `_truncate_project_text_for_a4`. After A4 returns and validates: `generated_dict = _restore_truncated_project_text(cv_data_out.model_dump(), cv_data_full)`. `generated_fields.json["generated"]` is written from `generated_dict` instead of `cv_data_out.model_dump()`.

This closes the Issue M leak: the truncated A4-input text (with `"…"` suffix) is no longer written to the artifact. The rendered document will contain the full original project descriptions.

### Modified files (2)

- `pipeline/utils/cefr.py`
- `pipeline/agents/fields_generator.py`

### Tests updated / added

- `tests/test_cefr_map.py` — `NUMERIC_SCALE_TO_CEFR` imported; `TestNumericScaleSentinel` → `TestNumericScaleMapping` with revised asserts and new cases; parenthetical-numeric test updated.
- `tests/test_cv_extractor_cefr.py` — `test_numeric_raw_produces_sentinel` updated to `test_numeric_raw_in_range_maps_to_cefr`; 2 new tests (`test_numeric_raw_out_of_range_produces_sentinel`, `test_slash_separated_raw_maps_each_digit`).
- `tests/test_fields_generator_text_cap.py` — `_restore_truncated_project_text` imported; `TestRestoreTruncatedProjectText` class with 9 tests.

### Documentation updated (5)

- `additions/PIPELINE_DIAGNOSTIC_CONTEXT.md` — Issues G/M marked fixed; Fix M section marked implemented; Round 3 record added.
- `markdowns/PROMPT_REVIEW_CONTEXT.md` — 2 new rows in §5 implementation status; §7 quickref extended.
- `markdowns/PROMPT_REVIEW_IMPLEMENTATION.md` (this file) — Round 4 section.
- `markdowns/PIPELINE_CONTEXT.md` — `fields_generator` pre-processing row updated.
- `markdowns/RUNS_ARTIFACTS_CONTEXT.md` — `generated_fields.json` row updated.

**Total Round 4**: 7 files touched, 294/294 tests passing (17 new/updated tests).

---

## Round 5 — Diagnostic Fixes Round 4 (May 2026)

Implements Fix N, Fix P, Fix Q, Fix O, Fix R from `additions/PIPELINE_DIAGNOSTIC_CONTEXT.md`.
Fix 4, Fix 2, and Fix 5b deferred to Round 6.

### Fix N — Project floor / threshold / cap recalibration

`pipeline/agents/cv_tor_mapper.py`:
- `MIN_PROJECTS_TO_KEEP = 3` (was 2). `MAX_PROJECTS_TO_KEEP = 10` (was 6).
- `_compute_threshold` returns `0.30 / 0.40 / 0.50` for `≤5 / ≤10 / >10` projects
  (previously `0.40 / 0.50 / 0.60`). Calibrated to retain borderline-relevant
  projects scoring 0.30–0.49 that were being discarded under the previous values.
- `_enforce_threshold_and_cap`: `effective_floor = min(MIN_PROJECTS_TO_KEEP, total)`
  at top of function — prevents infinite-loop hazard on thin CVs.
- `SYSTEM_PROMPT_A3` threshold table updated to mirror new Python values.
  New `test_prompt_threshold_values_match_python` test guards future drift.

### Fix P — A4 source preference for candidate KQ bullets

`SYSTEM_PROMPT_A4` in `pipeline/agents/fields_generator.py`:
- New `#### Source preference: condense the candidate's own KQ when bullet-style`
  subsection under GIZ key_qualifications. When 2+ bullet-style entries exist and
  are ToR-aligned, A4 selects + condenses rather than generating from scratch.
  Three from-scratch trigger conditions documented. `source` field guidance added.

### Fix Q — A1 other_skills routing

`SYSTEM_PROMPT_A1` in `pipeline/agents/cv_extractor.py`:
- New `### Other skills / Certifications / Training routing` section.
  Label-driven routing: source document label determines field destination.
  Both sections populated independently when both labels exist.

### Fix O — Numeric CEFR scale direction + default flip

`pipeline/utils/cefr.py`:
- `NUMERIC_SCALE_TO_CEFR` rewritten to "1_best" default (`1→C2, 2→C1, 3→B2,
  4→B1, 5→A2`). Breaking change from Round 3's `1→C1` default.
- `NUMERIC_SCALE_TO_CEFR_INVERTED` added for "1_worst" (`1→A1 … 5→C1`).
- Public `map_numeric_scale_inverted(token)` helper added.

`models.py`:
- `from typing import Literal` added. `language_scale_direction: Literal["1_best",
  "1_worst"] | None = Field(default=None, ...)` added to `CVData`.

`pipeline/agents/cv_extractor.py`:
- `_apply_cefr_with_direction(raw, direction)` helper routes to default or inverted
  mapping based on `language_scale_direction`.
- `_populate_cefr_fields` uses the direction-aware helper.
- `SYSTEM_PROMPT_A1`: `### Numeric language scale direction` subsection added under
  `### Language fields` — documents `"1_best"` / `"1_worst"` / null detection.

### Fix R — references + certification_declaration

`models.py`:
- `Reference(BaseModel)` class with `name`, `title`, `organisation`, `email`,
  `phone` (all `str = ""`).
- `CVData.references: list[Reference] = Field(default_factory=list)`.
- `CVData.certification_declaration: str = Field(default="")`.

`pipeline/agents/cv_extractor.py` (`SYSTEM_PROMPT_A1`):
- `### References` and `### Certification / Declaration` sections added.

`templates/giz.py` and `templates/wb.py` `_build_context`:
- `"references"` and `"certification_declaration"` keys added to return dict.
- Static `.docx` templates lack placeholders — rendering deferred to manual edit.

### New files (3)

- `tests/test_cv_extractor_prompt.py` — 8 tests (Q routing, O direction, R sections)
- `tests/test_models.py` — 14 tests (Reference, CVData new fields, backward compat)

### Modified files (9)

- `pipeline/agents/cv_tor_mapper.py`
- `pipeline/agents/fields_generator.py`
- `pipeline/agents/cv_extractor.py`
- `pipeline/utils/cefr.py`
- `models.py`
- `templates/giz.py`
- `templates/wb.py`
- `tests/test_cv_tor_mapper.py` (constant/threshold updates + 2 new tests)
- `tests/test_fields_generator_prompt.py` (3 new tests)
- `tests/test_cefr_map.py` (1_best defaults + `TestInvertedNumericScale` class)
- `tests/test_cv_extractor_cefr.py` (assertions updated + 1 new direction test)

### Documentation updated (6)

- `additions/PIPELINE_DIAGNOSTIC_CONTEXT.md` — Issues N–R marked fixed; Section 3 Round 4 completed; Round 5 added; Section 4 round table updated; Fix R static-template note in §5.
- `additions/PIPELINE_DIAGNOSTIC_ROUND_4.md` — Full implementation record in Round 3 format.
- `markdowns/PROMPT_REVIEW_CONTEXT.md` — 7 new rows in §5; §7 quickref extended.
- `markdowns/PROMPT_REVIEW_IMPLEMENTATION.md` (this file) — Round 5 section.
- `markdowns/PIPELINE_CONTEXT.md` — `cv_tor_mapper` and `cv_extractor` rows updated.
- `markdowns/RUNS_ARTIFACTS_CONTEXT.md` — `cv_data.json` row updated.

**Total Round 5**: 14 files touched, 332/332 tests passing (38 new/updated tests).

---

## Round 6 — Diagnostic Fixes Round 5 (May 2026)

Implements Fix U, Fix 2, Fix 4b, Fix 4, and Fix 5b from
`additions/PIPELINE_DIAGNOSTIC_CONTEXT.md`. Fix S deferred (calibration data
pending). Full detail in `additions/PIPELINE_DIAGNOSTIC_ROUND_5.md`.

### Fix U — A1 unfilled placeholder detection

`SYSTEM_PROMPT_A1`: `### Unfilled placeholder detection` section added.
A1 extracts faithfully; appends `extraction_warnings` entry when it detects
standalone uppercase letters in numeric context, bracket-delimited gaps, or
underscore gaps. Explicit exclusions for legitimate technical abbreviations.

### Fix 2 — All agents to Sonnet

`pipeline/config.py`: `ANTHROPIC_MODEL = "claude-sonnet-4-20250514"` (was Haiku).
All five agents (A1/A2/A3/A5/A6) pick up the change from the module import.

### Fix 4b — A2 `scoring_keywords`

`models.py`: `ScoringKeywords` class + `DistilledToR.scoring_keywords` field.
`SYSTEM_PROMPT_A2`: `### Scoring keywords` section — `role_implied` (inferred
from position title; Sonnet-class reasoning), `scope_implied` (from project scope),
`explicit` (stated requirements). 5–15 keywords per list.

### Fix 4 — Python relevance scoring

`pipeline/precompute_utils.py`: `keyword_overlap_score`, `geography_score`,
`compute_composite_score` added. `pipeline/agents/cv_tor_mapper.py`:
`_precompute_project_dates_for_mapper` (duration upstream); `_precompute_relevance_scores`
real implementation (stub replaced); `SYSTEM_PROMPT_A3` gains `## Pre-computed scores`
section. `pipeline/agents/fields_generator.py`: pre-compute call removed (now
in A3's `run()`).

### Fix 5b — Soft-flag manifest warnings

`pipeline/manifest.py`: `append_warning` helper. `pipeline/validators.py`: three
check functions (`check_fields_generator_warnings`, `check_content_reviewer_warnings`,
`check_compressor_warnings`). `pipeline/orchestrator.py`: soft-flag loops wired
after A4, A5, A6 in `run_phase3` and `_run_compressor_and_halt`.

### New files (3)

- `tests/test_tor_summarizer_prompt.py` — 4 tests
- `tests/test_manifest_warnings.py` — 5 tests
- `additions/PIPELINE_DIAGNOSTIC_ROUND_5.md` — full implementation record

### Modified files (13)

- `pipeline/config.py`, `pipeline/agents/cv_extractor.py`, `pipeline/agents/tor_summarizer.py`
- `pipeline/agents/cv_tor_mapper.py`, `pipeline/agents/fields_generator.py`
- `pipeline/manifest.py`, `pipeline/orchestrator.py`
- `pipeline/precompute_utils.py`, `pipeline/validators.py`, `models.py`
- `tests/test_cv_extractor_prompt.py`, `tests/test_models.py`
- `tests/test_precompute_utils.py`, `tests/test_cv_tor_mapper.py`
- `tests/test_validators.py`, `tests/test_fields_generator_precompute.py`

### Documentation updated (7)

- `additions/PIPELINE_DIAGNOSTIC_CONTEXT.md` — Issues C/D/U fixed; Fixes 2/4/4b/5b/U implemented; Round 5 completed; Round 6 added.
- `additions/PIPELINE_DIAGNOSTIC_ROUND_5.md` — new per-round record.
- `markdowns/RELEVANCE_SCORING_DESIGN.md` — status updated to IMPLEMENTED.
- `markdowns/PROMPT_REVIEW_CONTEXT.md` — 5 new implementation rows + §7 extended.
- `markdowns/PROMPT_REVIEW_IMPLEMENTATION.md` (this file) — Round 6 section.
- `markdowns/PIPELINE_CONTEXT.md` — tor_summarizer and cv_tor_mapper rows updated.
- `markdowns/RUNS_ARTIFACTS_CONTEXT.md` — tor_data.json and manifest.json rows updated.

**Total Round 6**: 18 files touched, 393/393 tests passing (61 new/updated tests).

---

## Round 7 — Diagnostic Fixes Round 6 (May 2026)

Implements Fix Z, Fix AA, Fix V, Fix W, Fix Y from `PIPELINE_DIAGNOSTIC_ROUND_6.md`.
Also includes Fix CC (employment-only fallback field mapping) aligned into Round 6 documentation.
Fix S and Fix 4 threshold recalibration deferred to Round 7.

### Files changed

| File | Change |
|------|--------|
| `pipeline/agents/compressor.py` | Fix Z: `A6_INPUT_PROJECT_WORD_CAP`, `_A6_CAPPED_FIELDS`, `_truncate_project_text_for_a6`; call site + `append_warning` loop in `run()`; `copy` and `append_warning` imports |
| `pipeline/agents/fields_generator.py` | Fix AA: `SYSTEM_PROMPT_A4` minimum output guarantee extended with explicit `detailed_tasks` example and geographic exemption rule |
| `pipeline/agents/cv_extractor.py` | Fix V: `### Merged-cell and two-column project tables` section in `SYSTEM_PROMPT_A1`; Fix W: `### Date ordering validation` section in `SYSTEM_PROMPT_A1` |
| `pipeline/agents/tor_summarizer.py` | Fix Y: `### scoring_keywords` section moved to immediately after `### position_title`; non-empty guarantee added |
| `pipeline/agents/cv_extractor.py` | Fix CC: `### Employment-only fallback (all formats)` section aligned to `description → main_project_features`; `employer → project_name + company`; `activities_performed / client / donor = ""`; warning wording aligned to `main_project_features` |
| `pipeline/validators.py` | Fix Y: `check_tor_summarizer_warnings` function |
| `pipeline/orchestrator.py` | Fix Y: `check_tor_summarizer_warnings` imported and wired in `run_phase1` after A2 |
| `tests/test_compressor_text_cap.py` | **New file.** 12 tests for `_truncate_project_text_for_a6` |
| `tests/test_fields_generator_prompt.py` | 2 new tests (`test_detailed_tasks_explicitly_mentioned`, `test_geographic_mismatch_does_not_exempt`) |
| `tests/test_cv_extractor_prompt.py` | 8 new tests (`TestSystemPromptA1MergedCellExtraction`, `TestSystemPromptA1DateOrdering`, employment-fallback mapping markers) |
| `tests/test_employment_fallback.py` | **New file.** 20 tests for `_apply_employment_fallback` mapping, warnings, and idempotence |
| `tests/test_tor_summarizer_prompt.py` | 2 new tests (`test_scoring_keywords_section_position`, `test_scoring_keywords_non_empty_guarantee_present`) |
| `tests/test_validators.py` | 6 new tests (`TestCheckTorSummarizerWarnings`) |
| `additions/PIPELINE_DIAGNOSTIC_CONTEXT.md` | Status header, issue headings, fix table, sequence, round summary updated |
| `additions/ISSUE_CC_CONTEXT.md` | Status and mapping semantics aligned to Round 6 (Fix CC) |
| `additions/PIPELINE_DIAGNOSTIC_ROUND_6.md` | Status → Complete; planned → delivered; implementation record added |
| `markdowns/PROMPT_REVIEW_CONTEXT.md` | 6 new rows + §7 quickref updated |
| `markdowns/PROMPT_REVIEW_IMPLEMENTATION.md` | This section |
| `markdowns/PIPELINE_CONTEXT.md` | A1 + Compressor rows updated |
| `markdowns/RUNS_ARTIFACTS_CONTEXT.md` | `cv_data.json` + `tor_data.json` + `manifest.json` rows updated |

**Total Round 7**: 19 files touched, 461/461 tests passing (48 new tests).

---

## Round 8 — Diagnostic Fixes Round 7 (May 2026)

Implements Fix DD, EE, FF-A, FF-B, GG, HH, R7-5, II-A, II-B, JJ, KK, LL, MM from
`PIPELINE_DIAGNOSTIC_ROUND_7.md`. Fix S and Fix 4 threshold recalibration deferred to Round 9.

### Fix JJ — Remove A4 truncation-and-restore (redundant with current model)

`pipeline/agents/fields_generator.py`: `_truncate_project_text_for_a4`,
`_restore_truncated_project_text`, `A4_INPUT_PROJECT_WORD_CAP`, `_A4_CAPPED_FIELDS`,
`cv_data_full` preservation, and the related `import logging` all removed. A4 now
receives full untruncated project text directly from `mapped_cv.json`.

### Fix KK — Remove A6 truncation entirely (silent data loss)

`pipeline/agents/compressor.py`: `_truncate_project_text_for_a6`,
`A6_INPUT_PROJECT_WORD_CAP`, `_A6_CAPPED_FIELDS`, all call sites, and all
`input_field_truncated` manifest warning emissions removed. A6 receives full project
text. `import copy` and truncation-related `append_warning` calls removed.

### Fix LL — A6 donor-aware compression

`pipeline/agents/compressor.py`: `run()` checks `manifest.params.donor`. For GIZ
runs, a deep copy (`cv_data_for_a6`) is made with `activities_performed` cleared on
all projects before word-count computation and the A6 LLM call. After the LLM
returns, original `activities_performed` values are restored from `cv_data_in`.
`SYSTEM_PROMPT_A6` updated with a note explaining GIZ field exclusion.

### Fix EE — Post-cap chronological sort at mapper write-time

`pipeline/agents/cv_tor_mapper.py`: `_parse_date` imported from
`pipeline.precompute_utils`. `_date_sort_key` and `_sort_by_date_desc` helper
functions added. Both `relevant_projects` and `countries_of_experience` sorted
descending by `date_from` (tie-break: `date_to`) after `_enforce_threshold_and_cap`,
before `CVData.model_validate`. Ensures WB `detailed_tasks[i]` ↔
`relevant_projects[i]` positional pairing is stable for A4 and the WB renderer.

### Fix II-A — WB renderer positional pairing documented

`templates/wb.py`: comment added to `_build_context` on the `tasks_assigned`
assembly loop documenting that position `i` of `detailed_tasks` corresponds to
position `i` of `relevant_projects` and that correctness relies on Fix EE's
sort being applied at mapper write-time.

### Fix II-B — A7 renderer-aware field mapping

`pipeline/agents/field_editor.py`:
- `RENDERER_FIELD_MAP` dict: per-donor set of project-level fields that are
  actually rendered (GIZ: `main_project_features`, `positions_held`; WB: adds
  `activities_performed`).
- `_RENDERER_REDIRECT_MAP` dict: field-level redirects (e.g.
  `activities_performed` → `main_project_features` for GIZ).
- `_check_renderer_field(field_key, donor)` function: returns `("render", ...)`
  / `("redirect", target)` / `("skip", reason)`.
- `run_field_editor()` calls `_check_renderer_field` after path resolution;
  skips the LLM call and returns an explanatory message on `"skip"`.
- `SYSTEM_PROMPT_A7` updated with `## DONOR-AWARE FIELD PATHS` section explaining
  field redirection and skipping.

### Fix DD — A1 prompt: citations routing

`pipeline/agents/cv_extractor.py`: `SYSTEM_PROMPT_A1` updated — "References"
sections containing academic citations (author, title, journal/year) route to
`publications[]`; contact references (name, organisation, email/phone) route to
`references[]`.

### Fix FF-A — A1 prompt: certifications dual-routing

`pipeline/agents/cv_extractor.py`: `SYSTEM_PROMPT_A1` updated — formal engineering
or professional credentials (e.g. "Eur Ing", "C Eng") are dual-routed to both
`certifications[]` and `membership_professional_bodies`.

### Fix FF-B — A4 prompt: certifications as KQ evidence source

`pipeline/agents/fields_generator.py`: `SYSTEM_PROMPT_A4` updated — `certifications[]`
added to the evidence sources list for generating key qualification bullets.

### Fix GG — GIZ education date duplication

`templates/giz.py`: the `f"{institution} [{date_range}]"` string construction
removed; `institution` now carries only the institution name. Single-year diploma
fallback: if `date_from` is empty, it is filled from `date_obtained`.

### Fix HH — GIZ renderer ampersand escaping

`templates/giz.py`: `import html as _html` added; `_xml_str(s)` helper applies
`html.escape()` to all string values before they are inserted into the Jinja2
context dict. Covers education, language, skills, projects, identity, KQ bullets,
publications, and reference sub-fields.

### Fix R7-5 — GIZ education rows newest-first sort

`templates/giz.py`: `_parse_date` imported from `pipeline.precompute_utils`;
`_edu_date_sort_key()` helper added. Education list sorted descending by `date_to`
(then `date_obtained`, then `date_from`) before processing in `_build_context`.

### Fix MM — API warning endpoint

`api/models/requests.py`: `WarningEntry` and `WarningsResponse` Pydantic models added.
`api/routers/sessions.py`: `GET /sessions/{id}/warnings` endpoint added — aggregates
`extraction_warnings` from `cv_data.json`, `alignment.warnings` from `mapped_cv.json`,
`warnings` from `manifest.json`, and `generation_warnings` from `generated_fields.json`;
returns a `WarningsResponse`.

### Files changed

| File | Change |
|------|--------|
| `pipeline/agents/fields_generator.py` | Fix JJ: truncation helpers + constants removed |
| `pipeline/agents/compressor.py` | Fix KK + LL: truncation removed; donor-aware exclusion added |
| `pipeline/agents/cv_tor_mapper.py` | Fix EE: `_sort_by_date_desc` + `_date_sort_key` + `_parse_date` import |
| `pipeline/agents/cv_extractor.py` | Fix DD + FF-A: `SYSTEM_PROMPT_A1` routing rules updated |
| `pipeline/agents/field_editor.py` | Fix II-B: `RENDERER_FIELD_MAP`, `_RENDERER_REDIRECT_MAP`, `_check_renderer_field`, `SYSTEM_PROMPT_A7` update |
| `templates/giz.py` | Fix GG + HH + R7-5: date duplication removed; `_xml_str` helper; education sort |
| `templates/wb.py` | Fix II-A: positional pairing dependency comment added |
| `api/models/requests.py` | Fix MM: `WarningEntry`, `WarningsResponse` models |
| `api/routers/sessions.py` | Fix MM: `GET /sessions/{id}/warnings` endpoint |
| `additions/PIPELINE_DIAGNOSTIC_ROUND_7.md` | Status → Complete; implementation record added |
| `additions/PIPELINE_DIAGNOSTIC_CONTEXT.md` | Status header, fix table, sequence, round summary updated |
| `markdowns/PROMPT_REVIEW_CONTEXT.md` | 10 new implementation rows; §7 quickref updated; §3 Fix LL note added |
| `markdowns/PROMPT_REVIEW_IMPLEMENTATION.md` | This section |
| `markdowns/PIPELINE_CONTEXT.md` | fields_generator + compressor rows updated; cv_tor_mapper Fix EE row added |
| `markdowns/RUNS_ARTIFACTS_CONTEXT.md` | `mapped_cv.json` + `generated_fields.json` + `manifest.json` rows updated |

**Total Round 8**: 15 files touched.
