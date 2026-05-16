# Pipeline Diagnostic — Round 3 Implementation Record

**Date**: May 2026
**Status**: Complete
**Tests after round**: 294/294 passing

---

## Fixes delivered

### Fix M Part 1 — Numeric 1–5 CEFR scale mapping

**Problem**: Round 2 production validation (Runs 3 and 4) confirmed that the `"?"`
sentinel introduced in Fix 7 renders in the Word document language table, producing
unprofessional output. The correct behaviour — confirmed from a reference document
screenshot — is to map the 1–5 numeric scale to CEFR codes. Run 4 Round 2 artifact
showed French `raw='3/4/4'` which should render as `B1/A2/A2`.

**Implementation**: `pipeline/utils/cefr.py`:
- `NUMERIC_SCALE_TO_CEFR` mapping dict: `{1: "C1", 2: "B2", 3: "B1", 4: "A2", 5: "A1"}`.
- `_try_numeric_scale(value)` helper.
- `_map_numeric_or_sentinel(value)` — maps bare integers 1–5 to CEFR labels,
  slash-separated all-in-range digits to slash-joined labels (`"3/4/4"` → `"B1/A2/A2"`),
  integers outside 1–5 to `"?"`.
- `_BARE_INT_PATTERN` and `_SLASH_NUMERIC_PATTERN` regexes added.
- `map_cefr` rewritten with full numeric-scale support.
- Module docstring updated.

`tests/test_cefr_map.py` updated: `TestNumericScaleSentinel` renamed to
`TestNumericScaleMapping` with revised + new assertions; new cases for 3-element
slash strings and out-of-range inputs.

`tests/test_cv_extractor_cefr.py` updated:
- `test_numeric_raw_produces_sentinel` → `test_numeric_raw_in_range_maps_to_cefr`.
- Added `test_numeric_raw_out_of_range_produces_sentinel`.
- Added `test_slash_separated_raw_maps_each_digit`.

**Residual confirmed in Round 3 production validation**: The mapping assumes
`1 = C1` (lowest = best CEFR). Run 4 (Merita Kostari) confirmed this is inverted
for CVs that use `"1 – excellent; 5 – basic"` convention, where `1 = C2`. Tracked
as Issue O; planned as Fix O in Round 4.

---

### Fix M Part 2 — Fix 8 Part 3 truncation-text restoration

**Problem**: Run 6 Round 2 (WB format) — A5 flagged a high-severity finding on
`relevant_projects[0].activities_performed`: text truncated mid-sentence ending
with `"…"`. `_truncate_project_text_for_a4` was applying truncation before user
message assembly but the truncated dict — not the original — was being written
into `generated_fields.json["generated"]` after A4 returned. The full text remained
intact in `mapped_cv.json` but was never restored.

**Implementation**: `pipeline/agents/fields_generator.py`:
- `import logging` and `log` module logger added.
- `_restore_truncated_project_text(cv_data_out, original_cv_data)` helper added —
  unconditional per-project restoration from pre-truncation copy, following the
  `restore_protected_fields` pattern in `precompute_utils.py`. Not marker-dependent.
  Skips with a warning log if project counts differ.
- In `run()`: `cv_data_full` assigned from the pre-truncation `cv_data` (after
  date pre-fill). After A4 returns and is validated,
  `_restore_truncated_project_text(cv_data_out.model_dump(), cv_data_full)` restores
  `activities_performed` and `main_project_features` from `cv_data_full` before the
  artifact is written to `generated_fields.json["generated"]`.

`tests/test_fields_generator_text_cap.py`: `_restore_truncated_project_text`
imported; `TestRestoreTruncatedProjectText` class with 9 tests added.

---

## Files changed

| File | Change |
|------|--------|
| `pipeline/utils/cefr.py` | `NUMERIC_SCALE_TO_CEFR` dict; `_try_numeric_scale`; `_map_numeric_or_sentinel`; `_BARE_INT_PATTERN`; `_SLASH_NUMERIC_PATTERN`; `map_cefr` rewritten with full numeric-scale support; module docstring updated. |
| `pipeline/agents/fields_generator.py` | `import logging`; `log` module logger; `_restore_truncated_project_text` helper; `cv_data_full` reference in `run()`; `_restore_truncated_project_text` call before artifact write. |
| `tests/test_cefr_map.py` | `NUMERIC_SCALE_TO_CEFR` imported; `TestNumericScaleSentinel` renamed to `TestNumericScaleMapping` with revised + new assertions; parenthetical-numeric test updated. |
| `tests/test_cv_extractor_cefr.py` | `test_numeric_raw_produces_sentinel` → `test_numeric_raw_in_range_maps_to_cefr`; added `test_numeric_raw_out_of_range_produces_sentinel`; added `test_slash_separated_raw_maps_each_digit`. |
| `tests/test_fields_generator_text_cap.py` | `_restore_truncated_project_text` imported; `TestRestoreTruncatedProjectText` class with 9 tests. |

---

## Test results

**294/294 tests passing after Round 3.**

---

## Production validation

| Run | CV type | Result | Notes |
|-----|---------|--------|-------|
| R3-Run 4 | GIZ, Merita Kostari, 24 projects, numeric language scale (1=best) | Partial | Fix M Part 1 confirmed: CEFR numeric mapping fires. Residual: scale direction inverted (1→C1 but source states 1=excellent=C2) — Issue O. Only 6 projects vs 18 expected — Issue N confirmed. A4 KQ bullets thematic rather than duration-based — Issue P. `other_skills` empty despite source section — Issue Q. `place_of_residence` empty — verified absent from source, closed. |
| R3-Run 5 | GIZ, Jennifer Garvey, 12 projects, weak geographic alignment (South Africa ToR) | Partial | Only 2 projects kept — Issue N confirmed critical. A5 Flag 2 (experience gap) artificial — caused by project dropping. A5 Flag 1 (South Africa absence) legitimate — genuine candidate gap. `threshold_used: null` and `pool: null` in alignment block — Fix J metadata write may not be firing for this run. |
| R3-Run 6 | WB format, Rafael Jabba, trick run (input was human-polished 12-project CV) | Partial | Fix M Part 2 confirmed: no truncation leak. Only 2 projects vs 12 expected — Issue N most critical finding. A5 Flag 2 (experience gap) entirely artificial due to project dropping. A5 Flag 1 (date mismatch) legitimate minor finding. `references` and `certification_declaration` absent — Issue R. |

---

## Issues surfaced in Round 3 production validation

| Issue | Run | Description | Planned fix |
|-------|-----|-------------|-------------|
| N | Runs 4, 5, 6 | A3 over-dropping: 2–6 projects from 12–24 histories | Fix N (Round 4) |
| O | Run 4 | CEFR numeric scale direction inverted for `1=best` CVs | Fix O (Round 4) |
| P | Run 4 | A4 synthesises new KQ bullets instead of using candidate's own | Fix P (Round 4) |
| Q | Run 4 | `other_skills` empty; data in `certifications` instead | Fix Q (Round 4) |
| R | Run 6 | `references` and `certification_declaration` absent from schema | Fix R (Round 4) |
| — | Run 4 | `place_of_residence` empty — verified absent from source document | Closed (not a bug) |

---

## Markdowns updated

`PIPELINE_DIAGNOSTIC_CONTEXT.md`, `PIPELINE_DIAGNOSTIC_ROUND_3.md` (this file),
`PROMPT_REVIEW_CONTEXT.md`, `PROMPT_REVIEW_IMPLEMENTATION.md`,
`PIPELINE_CONTEXT.md`, `RUNS_ARTIFACTS_CONTEXT.md`.

---

## Design decisions recorded

**Fix M Part 1 numeric mapping**: `1→C1` assumed as default (1 = lowest proficiency
= highest CEFR). Confirmed inverted for some CV templates — scale direction
detection deferred to Fix O (Round 4).

**Fix M Part 2 restoration strategy**: Unconditional per-project restoration from
pre-truncation copy. Not marker-dependent — A4's prompt forbids writing these
fields, so restoration is always semantically correct. Follows
`restore_protected_fields` pattern from `precompute_utils.py`.
