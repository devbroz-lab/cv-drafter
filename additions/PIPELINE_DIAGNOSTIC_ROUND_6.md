# Pipeline Diagnostic — Round 6 Implementation Record

**Date**: May 2026
**Status**: ✓ Complete
**Tests after round**: 461/461 passing

---

## Fixes delivered

### R6-E — Word cap on A6 (compressor) input

**Problem**: Run 6 of Round 5 — compressor hard failure. A6 received 1,696 words
of `activities_performed` across 5 projects (first project: 694 words), exceeding
its effective output budget and producing a truncated mid-JSON response. Fix 8
Part 3 caps A4's input but A4 can expand content in its output; Fix M Part 2
correctly restores originals — so A6 sees the full untruncated volume with no
equivalent cap.

**Scope**: `pipeline/agents/compressor.py` — pre-processing before user message
assembly. Mirrors Fix 8 Part 3 pattern.

**Planned changes**:
- Add `A6_INPUT_PROJECT_WORD_CAP` constant (suggested: 150 words, same as A4).
- Add `_truncate_project_text_for_a6(cv_data)` helper — operates on a deep copy,
  truncates `activities_performed` and `main_project_features` per project, suffixes
  with `"…"`.
- Call before user message assembly in `compressor.run()`.
- Original text is already preserved in `generated_fields.json`; no restoration
  step needed (A6 writes `fields_shortened` diffs, not full field content).

**Tests**: New file `tests/test_compressor_text_cap.py` — mirrors
`tests/test_fields_generator_text_cap.py` structure.

---

### R6-F — A4 minimum output guarantee extended to all `generative_field_keys`

**Problem**: Run 6 of Round 5 — WB format with `detailed_tasks` in
`generative_field_keys`. A4 produced 0 entries despite Fix 8 Part 2's minimum
output guarantee. Geographic mismatch (The Gambia) caused A4 to skip generation
for `detailed_tasks` entirely.

**Scope**: `SYSTEM_PROMPT_A4` in `pipeline/agents/fields_generator.py`. Prompt-only
change.

**Planned change**: Update the `### Minimum output guarantee` subsection to
explicitly reference all keys in `generative_field_keys`, not just
`key_qualifications`. Add language: "For every key listed in
`generative_field_keys`, you must produce at least one non-empty entry — including
`detailed_tasks` for WB format runs. Geographic or alignment weakness does not
exempt any key from this requirement."

**Tests**: Extend `tests/test_fields_generator_prompt.py` with marker test for
the updated guarantee language.

---

### R6-D — A2 `scoring_keywords` prompt fix for PDF ToR input

**Problem**: Round 5 Run 4 (PDF ToR) — all three `scoring_keywords` lists empty
despite rich ToR content. Round 5 Run 5 (non-PDF ToR) confirmed R5-A working
correctly — the issue is PDF-specific, likely due to the extraction instruction
being deprioritised on long inputs or PDF text layout affecting A2's parsing.

**Scope**: `SYSTEM_PROMPT_A2` in `pipeline/agents/tor_summarizer.py`. Prompt-only
change.

**Planned changes**:
- Move the `### Scoring keywords` extraction section earlier in `SYSTEM_PROMPT_A2`
  so it is not deprioritised when input is long.
- Add explicit instruction that `scoring_keywords` must be populated regardless
  of input format (PDF or docx) and input length.
- Wire a soft-flag warning via R5-D's `check_content_reviewer_warnings`
  equivalent: if all three keyword lists are empty after A2, append a manifest
  warning.

**Tests**: Extend `tests/test_tor_summarizer_prompt.py` with position-of-section
and non-empty guarantee tests.

---

### R6-G — Employment-only fallback routing to project-overview fields

**Problem**: Round 6 Run 4 (Jennifer Garvey, GIZ, South Africa ToR) —
`relevant_projects` was empty while `employment_record` contained rich entries.
A3 had nothing to score, the rendered projects section went blank, and A4 had
insufficient project evidence for strong generation.

**Scope**: `pipeline/agents/cv_extractor.py` prompt and Python safety net.

**Planned changes**:
- In `SYSTEM_PROMPT_A1` `### Employment-only fallback (all formats)`, route
  `employment_record.description` to `relevant_projects.main_project_features`
  (not `activities_performed`).
- Keep `activities_performed` empty in fallback mode when source only provides
  employment descriptions.
- Align mapping semantics to Python fallback behavior:
  `employer → project_name + company`; `client` remains empty.
- Update short-detail warning wording to reference `main_project_features`.
- Update `_apply_employment_fallback` to mirror the same mapping so fallback is
  deterministic even when the LLM misses prompt instructions.

**Tests**:
- Extend `tests/test_cv_extractor_prompt.py` for fallback mapping markers.
- Add `tests/test_employment_fallback.py` to lock Python fallback routing and
  warning behavior.

---

## Deferred to Round 7

### Fix S — Compressor word target scaled to `page_limit`
Pending calibration data (5+ clean rendered outputs per template). See
`COMPRESSION_CALIBRATION_CONTEXT.md`.

### R5-B threshold recalibration
Review `MIN_PROJECTS_TO_KEEP` and `MAX_PROJECTS_TO_KEEP` constants (currently
`MIN=5`, `MAX=15` in code) once R5-B scoring produces a stable distribution
across sufficient production runs.

---

## Files to be changed

| File | Planned change |
|------|---------------|
| `pipeline/agents/compressor.py` | R6-E: `A6_INPUT_PROJECT_WORD_CAP` constant; `_truncate_project_text_for_a6` helper; called pre-assembly in `run()`. |
| `pipeline/agents/fields_generator.py` | R6-F: extend `### Minimum output guarantee` in `SYSTEM_PROMPT_A4`. |
| `pipeline/agents/cv_extractor.py` | R6-A + R6-B: extend `SYSTEM_PROMPT_A1` with merged-cell extraction and date ordering validation. |
| `pipeline/agents/tor_summarizer.py` | R6-D: reorder `SYSTEM_PROMPT_A2`; strengthen `scoring_keywords` guarantee. |
| `tests/test_compressor_text_cap.py` | **New file.** R6-E tests. |
| `tests/test_fields_generator_prompt.py` | R6-F: new prompt marker test. |
| `tests/test_cv_extractor_prompt.py` | R6-A + R6-B: new prompt instruction tests. |
| `tests/test_tor_summarizer_prompt.py` | R6-D: new position and guarantee tests. |

---

## Implementation sequence

1. ✓ R6-E — compressor word cap (hard failure — highest priority).
2. ✓ R6-F — A4 minimum output guarantee for all `generative_field_keys`.
3. ✓ R6-A — A1 merged-cell project name extraction.
4. ✓ R6-B — A1 date inversion auto-correct across all four date-field types.
5. ✓ R6-D — A2 `scoring_keywords` prompt fix + soft-flag validator.
6. ✓ R6-G — A1 employment-only fallback mapping + Python safety net alignment.

---

## Files changed

| File | Step | Nature |
|------|------|--------|
| `pipeline/agents/compressor.py` | R6-E | `A6_INPUT_PROJECT_WORD_CAP`, `_A6_CAPPED_FIELDS`, `_truncate_project_text_for_a6`; call site in `run()`; `append_warning` calls for truncation events; `copy` + `append_warning` imports |
| `pipeline/agents/fields_generator.py` | R6-F | `SYSTEM_PROMPT_A4` minimum guarantee — explicit `detailed_tasks` example + geographic exemption rule |
| `pipeline/agents/cv_extractor.py` | R6-A, R6-B | `SYSTEM_PROMPT_A1` — `### Merged-cell and two-column project tables`; `### Date ordering validation` |
| `pipeline/agents/tor_summarizer.py` | R6-D | `SYSTEM_PROMPT_A2` — `### scoring_keywords` moved to after `### position_title`; non-empty guarantee added |
| `pipeline/validators.py` | R6-D | `check_tor_summarizer_warnings` function added |
| `pipeline/orchestrator.py` | R6-D | `check_tor_summarizer_warnings` imported and wired in `run_phase1` |
| `tests/test_compressor_text_cap.py` | R6-E | **New file.** 12 tests |
| `tests/test_fields_generator_prompt.py` | R6-F | 2 new tests |
| `tests/test_cv_extractor_prompt.py` | R6-A, R6-B | 6 new tests |
| `tests/test_tor_summarizer_prompt.py` | R6-D | 2 new tests |
| `tests/test_validators.py` | R6-D | 6 new tests (`TestCheckTorSummarizerWarnings`) |
| `tests/test_employment_fallback.py` | R6-G | **New file.** 20 tests for `_apply_employment_fallback` mapping, warning text, and idempotence |
| `additions/PIPELINE_DIAGNOSTIC_CONTEXT.md` | Docs | Status, fix table, sequence, round summary updated |
| `additions/PIPELINE_DIAGNOSTIC_ROUND_6.md` | Docs | This file — status updated to Complete |
| `markdowns/PROMPT_REVIEW_CONTEXT.md` | Docs | 6 new rows + §7 updated |
| `markdowns/PROMPT_REVIEW_IMPLEMENTATION.md` | Docs | Round 7 section appended |
| `markdowns/PIPELINE_CONTEXT.md` | Docs | Compressor + A1 rows updated |
| `markdowns/RUNS_ARTIFACTS_CONTEXT.md` | Docs | cv_data.json + tor_data.json + manifest.json rows updated |

---

## Test results

461/461 passing (48 new tests added: 12 R6-E, 2 R6-F, 6 R6-A+W, 2 R6-D prompt, 6 R6-D validator, 20 R6-G fallback).

---

## Design decisions recorded

1. **R6-E — truncate-and-warn**: Information beyond 150 words per dense field is permanently excluded from A6's compression scope. The manifest soft-flag warning (`input_field_truncated`) surfaces every truncation event. No restore step (A6 is supposed to compress these fields). `append_warning` called directly from `compressor.run()`.

2. **R6-F — targeted reinforcement only**: Kept existing guarantee language; added explicit bullet for `detailed_tasks` and a statement that geographic/alignment weakness does not exempt any key.

3. **R6-A — empty with warning, no fabrication**: Leave `project_name = ""` when not determinable + emit `extraction_warnings` entry. No fabrication.

4. **R6-B — all four field types covered**: Date inversion check and auto-correct applied to all `date_from`/`date_to` pairs: `relevant_projects[]`, `education[]`, `employment_record[]`, `countries_of_experience[]`. "Present" always sorts later than any literal date.

5. **R6-D — new validator function**: `check_tor_summarizer_warnings` added to `pipeline/validators.py`; wired in `run_phase1` after `tor_summarizer.run`.
6. **R6-G — preserve renderer paragraph semantics**: Employment fallback now
   maps descriptive employment text to `main_project_features` (project overview)
   and leaves `activities_performed` empty (candidate-actions paragraph). This
   aligns fallback output with template paragraph ordering and prevents rich
   project text from appearing in the wrong block.

---

## Production validation

- Round 6 Run 4 surfaced Issue AB: employment-only CVs produced
  `relevant_projects: []`, causing blank rendered project sections.
- R6-G implemented in Round 6: A1 prompt fallback + Python safety net now
  dual-populate `relevant_projects` from `employment_record` using
  `description → main_project_features`.
- Validation expectation after fix: employment-only CVs now produce scored
  `relevant_projects` entries for A3/A4 and non-blank project sections in output.

---

## Issues surfaced in Round 6 production validation

- **Issue AB** — No relevant projects when CV uses employment-only format.
  Root cause: A3 scored only `relevant_projects` while A1 had routed content to
  `employment_record`. Resolution implemented in this round via R6-G.
