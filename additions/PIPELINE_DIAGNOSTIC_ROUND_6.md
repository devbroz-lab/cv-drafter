# Pipeline Diagnostic — Round 6 Implementation Record

**Date**: May 2026
**Status**: ✓ Complete
**Tests after round**: 421/421 passing

---

## Fixes delivered

### Fix Z — Word cap on A6 (compressor) input

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

### Fix AA — A4 minimum output guarantee extended to all `generative_field_keys`

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

### Fix Y — A2 `scoring_keywords` prompt fix for PDF ToR input

**Problem**: Round 5 Run 4 (PDF ToR) — all three `scoring_keywords` lists empty
despite rich ToR content. Round 5 Run 5 (non-PDF ToR) confirmed Fix 4b working
correctly — the issue is PDF-specific, likely due to the extraction instruction
being deprioritised on long inputs or PDF text layout affecting A2's parsing.

**Scope**: `SYSTEM_PROMPT_A2` in `pipeline/agents/tor_summarizer.py`. Prompt-only
change.

**Planned changes**:
- Move the `### Scoring keywords` extraction section earlier in `SYSTEM_PROMPT_A2`
  so it is not deprioritised when input is long.
- Add explicit instruction that `scoring_keywords` must be populated regardless
  of input format (PDF or docx) and input length.
- Wire a soft-flag warning via Fix 5b's `check_content_reviewer_warnings`
  equivalent: if all three keyword lists are empty after A2, append a manifest
  warning.

**Tests**: Extend `tests/test_tor_summarizer_prompt.py` with position-of-section
and non-empty guarantee tests.

---

## Deferred to Round 7

### Fix S — Compressor word target scaled to `page_limit`
Pending calibration data (5+ clean rendered outputs per template). See
`COMPRESSION_CALIBRATION_CONTEXT.md`.

### Fix 4 threshold recalibration
Review `MIN_PROJECTS_TO_KEEP` and `MAX_PROJECTS_TO_KEEP` constants (currently
`MIN=5`, `MAX=15` in code) once Fix 4 scoring produces a stable distribution
across sufficient production runs.

---

## Files to be changed

| File | Planned change |
|------|---------------|
| `pipeline/agents/compressor.py` | Fix Z: `A6_INPUT_PROJECT_WORD_CAP` constant; `_truncate_project_text_for_a6` helper; called pre-assembly in `run()`. |
| `pipeline/agents/fields_generator.py` | Fix AA: extend `### Minimum output guarantee` in `SYSTEM_PROMPT_A4`. |
| `pipeline/agents/cv_extractor.py` | Fix V + Fix W: extend `SYSTEM_PROMPT_A1` with merged-cell extraction and date ordering validation. |
| `pipeline/agents/tor_summarizer.py` | Fix Y: reorder `SYSTEM_PROMPT_A2`; strengthen `scoring_keywords` guarantee. |
| `tests/test_compressor_text_cap.py` | **New file.** Fix Z tests. |
| `tests/test_fields_generator_prompt.py` | Fix AA: new prompt marker test. |
| `tests/test_cv_extractor_prompt.py` | Fix V + Fix W: new prompt instruction tests. |
| `tests/test_tor_summarizer_prompt.py` | Fix Y: new position and guarantee tests. |

---

## Implementation sequence

1. ✓ Fix Z — compressor word cap (hard failure — highest priority).
2. ✓ Fix AA — A4 minimum output guarantee for all `generative_field_keys`.
3. ✓ Fix V — A1 merged-cell project name extraction.
4. ✓ Fix W — A1 date inversion auto-correct across all four date-field types.
5. ✓ Fix Y — A2 `scoring_keywords` prompt fix + soft-flag validator.

---

## Files changed

| File | Step | Nature |
|------|------|--------|
| `pipeline/agents/compressor.py` | Fix Z | `A6_INPUT_PROJECT_WORD_CAP`, `_A6_CAPPED_FIELDS`, `_truncate_project_text_for_a6`; call site in `run()`; `append_warning` calls for truncation events; `copy` + `append_warning` imports |
| `pipeline/agents/fields_generator.py` | Fix AA | `SYSTEM_PROMPT_A4` minimum guarantee — explicit `detailed_tasks` example + geographic exemption rule |
| `pipeline/agents/cv_extractor.py` | Fix V, Fix W | `SYSTEM_PROMPT_A1` — `### Merged-cell and two-column project tables`; `### Date ordering validation` |
| `pipeline/agents/tor_summarizer.py` | Fix Y | `SYSTEM_PROMPT_A2` — `### scoring_keywords` moved to after `### position_title`; non-empty guarantee added |
| `pipeline/validators.py` | Fix Y | `check_tor_summarizer_warnings` function added |
| `pipeline/orchestrator.py` | Fix Y | `check_tor_summarizer_warnings` imported and wired in `run_phase1` |
| `tests/test_compressor_text_cap.py` | Fix Z | **New file.** 12 tests |
| `tests/test_fields_generator_prompt.py` | Fix AA | 2 new tests |
| `tests/test_cv_extractor_prompt.py` | Fix V, Fix W | 6 new tests |
| `tests/test_tor_summarizer_prompt.py` | Fix Y | 2 new tests |
| `tests/test_validators.py` | Fix Y | 6 new tests (`TestCheckTorSummarizerWarnings`) |
| `additions/PIPELINE_DIAGNOSTIC_CONTEXT.md` | Docs | Status, fix table, sequence, round summary updated |
| `additions/PIPELINE_DIAGNOSTIC_ROUND_6.md` | Docs | This file — status updated to Complete |
| `markdowns/PROMPT_REVIEW_CONTEXT.md` | Docs | 6 new rows + §7 updated |
| `markdowns/PROMPT_REVIEW_IMPLEMENTATION.md` | Docs | Round 7 section appended |
| `markdowns/PIPELINE_CONTEXT.md` | Docs | Compressor + A1 rows updated |
| `markdowns/RUNS_ARTIFACTS_CONTEXT.md` | Docs | cv_data.json + tor_data.json + manifest.json rows updated |

---

## Test results

421/421 passing (28 new tests added: 12 Fix Z, 2 Fix AA, 6 Fix V+W, 2 Fix Y prompt, 6 Fix Y validator).

---

## Design decisions recorded

1. **Fix Z — truncate-and-warn**: Information beyond 150 words per dense field is permanently excluded from A6's compression scope. The manifest soft-flag warning (`input_field_truncated`) surfaces every truncation event. No restore step (A6 is supposed to compress these fields). `append_warning` called directly from `compressor.run()`.

2. **Fix AA — targeted reinforcement only**: Kept existing guarantee language; added explicit bullet for `detailed_tasks` and a statement that geographic/alignment weakness does not exempt any key.

3. **Fix V — empty with warning, no fabrication**: Leave `project_name = ""` when not determinable + emit `extraction_warnings` entry. No fabrication.

4. **Fix W — all four field types covered**: Date inversion check and auto-correct applied to all `date_from`/`date_to` pairs: `relevant_projects[]`, `education[]`, `employment_record[]`, `countries_of_experience[]`. "Present" always sorts later than any literal date.

5. **Fix Y — new validator function**: `check_tor_summarizer_warnings` added to `pipeline/validators.py`; wired in `run_phase1` after `tor_summarizer.run`.

---

## Production validation

*(Pending Round 6 production runs.)*

---

## Issues surfaced in Round 6 production validation

*(Pending Round 6 production runs.)*
