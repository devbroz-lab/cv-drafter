# Pipeline Diagnostic — Round 2 Implementation Record

**Date**: May 2026
**Status**: Complete
**Tests after round**: 277/277 passing

---

## Fixes delivered

### Fix 9 — Make `FieldShortened.subfield` optional in `models.py`

**Problem**: Run 4 produced a compressor failure with 23 Pydantic validation errors:
`"fields_shortened.N.subfield — Input should be a valid string [input_value=None]"`.
Agent 6 correctly outputs `subfield: null` for dot-path fields (where the full path
is already in `field`), but `FieldShortened.subfield` was typed as `str`, rejecting
`null`. The LLM's output was correct; the schema was too strict. Compression would
have succeeded (2336 → 1798 words against 1800 target) but the schema rejection
halted the step entirely.

**Implementation**: `models.py:515` — `subfield: str | None = Field(default=None, ...)`.
Backward-compatible: sessions with `subfield: ""` deserialise cleanly.

6 tests in `TestFieldShortenedOptionalSubfield` in
`tests/test_compressor_postprocessing.py`.

---

### Fix 7 — Normalise non-standard CEFR input formats in `map_cefr`

**Problem**: Two distinct normalisation failures confirmed:
- Parenthetical format: "Proficient (C2)" produced `reading_cefr: "Proficient (C2)"`.
- Numeric scale: language proficiency on a 1–5 scale produced `reading_cefr: "1"`.

**Implementation**: `pipeline/utils/cefr.py` extended with:
- `CEFR_UNRESOLVABLE_SENTINEL = "?"`.
- `_PAREN_PATTERN` regex — extracts CEFR code from parenthetical strings.
- `_NUMERIC_PATTERN` regex — detects numeric inputs.
- `map_cefr` rewritten to handle both cases. Numeric inputs return `"?"` sentinel
  at this stage (sentinel-to-CEFR mapping deferred to Fix M Part 1).

53 tests in `tests/test_cefr_map.py`. 2 integration tests added to
`tests/test_cv_extractor_cefr.py` (`TestPopulateCefrFieldsFix7Integration`).

**Note**: The `"?"` sentinel was confirmed rendering in the Word document during
Round 2 production validation (Runs 3 and 4). Fix M Part 1 (Round 3) replaced the
sentinel with a full numeric-to-CEFR mapping.

---

### Fix J + Fix 8 Part 1 — Python threshold enforcement + project cap

**Problem (Fix J)**: Run 4 showed A3 kept 18 of 24 projects despite a 0.60
threshold applying. Entries scoring 0.55–0.59 all survived. The LLM was
inconsistently applying its own threshold rule.

**Problem (Fix 8 Part 1)**: A3 had a floor but no ceiling. For large CVs (Run 3:
41 projects, 11 above threshold), the threshold alone was insufficient to bound
A4's input to a workable size.

**Implementation**: `pipeline/agents/cv_tor_mapper.py`:
- `MAX_PROJECTS_TO_KEEP = 6` constant added.
- `_compute_threshold(n_projects)` — returns 0.40/0.50/0.60 by project count
  bracket, mirroring the existing prompt rule.
- `_enforce_threshold_and_cap(projects, threshold)` — runs after LLM response is
  parsed and before `CVData.model_validate`. Deterministically: (1) drops any
  project below the computed threshold, (2) restores up to `MIN_PROJECTS_TO_KEEP`
  top-scoring dropped projects if needed, (3) truncates kept set to
  `MAX_PROJECTS_TO_KEEP`. Appends warning strings to the alignment block for each
  enforcement action.

23 tests in `tests/test_cv_tor_mapper.py` (new file) covering threshold, minimum
guarantee, cap, order, and composition.

---

### Fix 8 Part 3 — Per-project text cap in A4 pre-processing

**Problem (Issue L)**: Run 6 (World Bank format, 4 projects kept) produced a Fix 5a
hard-block failure. The top project alone had 694 words of `activities_performed`.
Total across 4 projects was ~1,497 words — comparable to Run 3's 11-project total
despite having only 4 projects. No per-project word cap existed.

**Implementation**: `pipeline/agents/fields_generator.py`:
- `import copy` at module level.
- `A4_INPUT_PROJECT_WORD_CAP = 150` constant.
- `_A4_CAPPED_FIELDS = ("activities_performed", "main_project_features")`.
- `_truncate_project_text_for_a4(cv_data)` helper — truncates each project's
  capped fields to 150 words, suffixing with `"…"`. Called between
  `_precompute_project_dates` and user message assembly.

`mapped_cv.json` on disk unchanged — only the A4 input is trimmed.

16 tests in `tests/test_fields_generator_text_cap.py` (new file).

**Note**: The truncated copy was confirmed leaking into `generated_fields.json`
during Run 6 production validation — tracked as Issue M, fixed in Round 3
(Fix M Part 2).

---

### Fix 8 Part 2 — A4 prompt priority order + minimum output guarantee

**Problem (Issue K)**: Run 5 (GIZ, 8 projects, weak alignment, zero geographic
match) produced a Fix 5a hard-block with 4 empty `generated_fields` entries.
Input size was not the problem — A4 on Sonnet declined to generate rather than
fabricate weakly-grounded content.

**Implementation**: `SYSTEM_PROMPT_A4` in `pipeline/agents/fields_generator.py`
extended with:
- `## OUTPUT PRIORITY ORDER` — instructs A4 to write `generated_fields` first,
  before any other field-filling or reasoning.
- `### Minimum output guarantee` — instructs A4 to always produce at least one
  non-empty entry per `generative_field_keys` key even when alignment is weak,
  grounding in whatever CV evidence exists and flagging low-confidence entries
  in `generation_warnings`.

9 tests in `tests/test_fields_generator_prompt.py` (new file) covering prompt
marker presence.

---

## Files changed

| File | Change |
|------|--------|
| `models.py` | `FieldShortened.subfield: str | None = Field(default=None, ...)` |
| `pipeline/utils/cefr.py` | `CEFR_UNRESOLVABLE_SENTINEL`, `_PAREN_PATTERN`, `_NUMERIC_PATTERN` added; `map_cefr` rewritten with parenthetical extraction and numeric-scale detection. |
| `pipeline/agents/cv_tor_mapper.py` | `MAX_PROJECTS_TO_KEEP = 6`; `_compute_threshold`; `_enforce_threshold_and_cap` (Fix J + Fix 8 Part 1); wired in `run()` before `CVData.model_validate`. |
| `pipeline/agents/fields_generator.py` | `import copy` at module level; `A4_INPUT_PROJECT_WORD_CAP = 150`; `_A4_CAPPED_FIELDS`; `_truncate_project_text_for_a4` (Fix 8 Part 3); called in `run()` after `_precompute_project_dates`. `SYSTEM_PROMPT_A4` extended with `## OUTPUT PRIORITY ORDER` and `### Minimum output guarantee` (Fix 8 Part 2). |
| `tests/test_cefr_map.py` | **New.** 53 tests for full `map_cefr` coverage. |
| `tests/test_cv_extractor_cefr.py` | 2 Fix 7 integration tests added (`TestPopulateCefrFieldsFix7Integration`). |
| `tests/test_compressor_postprocessing.py` | `TestFieldShortenedOptionalSubfield` — 6 tests. |
| `tests/test_cv_tor_mapper.py` | **New.** 23 tests. |
| `tests/test_fields_generator_text_cap.py` | **New.** 16 tests. |
| `tests/test_fields_generator_prompt.py` | **New.** 9 tests. |

---

## Test results

**277/277 tests passing after Round 2.**

---

## Production validation

| Run | CV type | Result | Notes |
|-----|---------|--------|-------|
| R2-Run 3 | GIZ, 23 projects, numeric language scale | Pass (pipeline) | Fix J + 8 Part 1 confirmed: 6 projects kept, all ≥0.81. `"?"` sentinel renders in doc — Fix M needed. |
| R2-Run 4 | GIZ, 24 projects, numeric language scale | Pass (pipeline) | Fix J confirmed: sub-threshold projects correctly dropped. `"?"` persists — Fix M needed. |
| R2-Run 5 | GIZ, short CV, weak alignment | Pass | Fix 8 Parts 1/2/3 confirmed. Min guarantee correctly restored 2 projects below threshold. Descriptive CEFR ("Excellent"→C2, "Good"→C1, "Fair"→B1/B2) confirmed working. |
| R2-Run 6 | WB format, dense projects | Pass (pipeline) | 4 `detailed_tasks` generated. Fix 8 Part 3 cap fired correctly. Truncation `"…"` leaked into `generated_fields.json` — Issue M confirmed, Fix M Part 2 needed. |

---

## Markdowns updated

`PIPELINE_DIAGNOSTIC_CONTEXT.md`, `PIPELINE_DIAGNOSTIC_ROUND_2.md` (this file),
`PROMPT_REVIEW_CONTEXT.md`, `PROMPT_REVIEW_IMPLEMENTATION.md`,
`PIPELINE_CONTEXT.md`, `RUNS_ARTIFACTS_CONTEXT.md`.

---

## Design decisions recorded

**Fix J threshold values**: `0.40 / 0.50 / 0.60` by project count bracket —
mirrors the existing prompt rule, making Python enforcement a post-LLM safety
net rather than a separate logic layer.

**`MAX_PROJECTS_TO_KEEP = 6`**: Chosen as a conservative cap to protect A4's
token budget. Confirmed too aggressive in Round 3 production validation (Issue N)
— raised to 10 in Fix N (Round 4).

**Fix 8 Part 3 word cap (150 words)**: Reduces a 694-word worst case to 150,
giving ~300 words max per project × 6 projects = ~1,800 words from projects alone.

**Fix 8 Part 3 truncation marker**: `"…"` (U+2026) chosen over `"... [truncated]"`
— consistent with existing pipeline conventions in `field_editor.py`.

**Fix 8 Part 3 restoration**: Confirmed necessary in Round 3 (Issue M) —
truncated copy was writing to artifact. Fix M Part 2 added
`_restore_truncated_project_text` to restore originals before artifact write.
