# Pipeline Diagnostic — Round 4 Implementation Record

**Date**: May 2026
**Status**: Complete
**Tests after round**: 332/332 passing

---

## Fixes delivered

### R4-A — Raise project floor, lower thresholds, raise project cap

**Problem**: Across Runs 4, 5, and 6 of Round 3, A3 consistently produced CVs
with only 2–6 projects from candidates with 12–24 project histories. Projects
scoring 0.45–0.72 representing genuine relevant experience were discarded. A CV
of 2 projects is not viable in any real-world submission context. The cap of 6
was introduced to protect A4's token budget — Fix 8 Parts 2 and 3 now provide
that protection independently of project count.

**Scope**: `pipeline/agents/cv_tor_mapper.py` — constants, `_compute_threshold`,
`_enforce_threshold_and_cap`, and the threshold table in `SYSTEM_PROMPT_A3`.

**Implementation**:
- `MIN_PROJECTS_TO_KEEP`: `2` → `3`.
- `MAX_PROJECTS_TO_KEEP`: `6` → `10`.
- `_compute_threshold`: `0.40 / 0.50 / 0.60` → `0.30 / 0.40 / 0.50`
  (for ≤5 / ≤10 / >10 projects).
- `_enforce_threshold_and_cap`: added `effective_floor = min(MIN_PROJECTS_TO_KEEP, total)`
  at the top of the function; used in the minimum-guarantee step instead of the
  bare constant. Prevents infinite-loop hazard on thin CVs (1–2 projects).
- `SYSTEM_PROMPT_A3` threshold table updated to match: `0.30 / 0.40 / 0.50`.
  New test `test_prompt_threshold_values_match_python` guards against future drift.

**Note**: These constants are interim values pending R5-B (Python relevance
scoring). Threshold calibration should be revisited once R5-B produces
consistent scores.

---

### R4-C — Guide Agent 4 to prefer candidate's own KQ text when already bullet-style

**Problem**: Round 3 Run 4 — A1 correctly extracted 9 bullet-style
`key_qualifications` matching the expected output style exactly. A4 discarded
them and generated new thematic bullets instead.

**Scope**: `SYSTEM_PROMPT_A4` in `pipeline/agents/fields_generator.py`. Prompt-only
change. No schema or code changes.

**Implementation**: Added `#### Source preference: condense the candidate's own KQ
when bullet-style` subsection under the GIZ `key_qualifications` section. Specifies:
- When 2+ bullet-style entries exist and are reasonably aligned with the ToR:
  SELECT, CONDENSE, and LIGHTLY EDIT rather than generating from scratch.
  Use `source = "experience"` for kept candidate bullets.
- Generate from scratch ONLY when: KQs are empty; entries are paragraph-style
  prose; or entries are clearly misaligned with the ToR.
- Mixing is acceptable (keep some candidate bullets, add one new ToR-grounded
  bullet for a gap). Mark each `source` field accurately.

---

### R4-D — Route `other_skills` correctly at Agent 1 extraction time

**Problem**: Round 3 Run 4 — source CV has a "Other skills" section with 6
entries. A1 routed the content to `certifications[]` but left `other_skills: []`
empty. The renderer reads `other_skills`, so the section renders blank.

**Scope**: `SYSTEM_PROMPT_A1` in `pipeline/agents/cv_extractor.py`. Prompt-only
change.

**Implementation**: Added `### Other skills / Certifications / Training routing`
section before `### Fields to leave empty — always`. Specifies label-driven routing:
- "Other skills" (or variants) → `other_skills`.
- "Certifications" → `certifications`.
- "Training" → `training`.
- "Membership in professional bodies" → `membership_professional_bodies`.
- Both sections populated independently when both labels exist in the source.

---

### R4-B — Detect numeric CEFR scale direction at Agent 1 extraction time

**Problem**: Round 3 Run 4 source CV states `"1 – excellent; 5 – basic"`,
meaning `1 = C2`. Fix M Part 1 mapped `1 → C1` (wrong direction). A1 correctly
flagged the ambiguity in `extraction_warnings` but the hard-coded mapping
overrode it.

**Scope**: `pipeline/utils/cefr.py`, `models.py`, `pipeline/agents/cv_extractor.py`.

**Implementation**:

`pipeline/utils/cefr.py`:
- `NUMERIC_SCALE_TO_CEFR` rewritten to the **"1_best" default** (1 = excellent):
  `1→C2, 2→C1, 3→B2, 4→B1, 5→A2`. This is the dominant convention in
  development-sector CVs and the correct default per Round 3 evidence.
- `NUMERIC_SCALE_TO_CEFR_INVERTED` added for the "1_worst" convention:
  `1→A1, 2→A2, 3→B1, 4→B2, 5→C1`.
- Public `map_numeric_scale_inverted(token)` helper added.
- Module docstring updated to describe both conventions.

`models.py`:
- `from typing import Literal` import added.
- `language_scale_direction: Literal["1_best", "1_worst"] | None = Field(default=None, ...)`
  added to `CVData` in the Extraction metadata group.

`pipeline/agents/cv_extractor.py`:
- `map_numeric_scale_inverted` imported from `pipeline.utils.cefr`.
- `_apply_cefr_with_direction(raw, direction)` private helper added — routes to
  default `map_cefr` or inverted mapping based on `language_scale_direction`.
- `_populate_cefr_fields` updated to read `parsed.language_scale_direction` and
  call `_apply_cefr_with_direction` instead of bare `map_cefr`.
- `SYSTEM_PROMPT_A1` extended: `### Numeric language scale direction` subsection
  under `### Language fields`. Documents `"1_best"` / `"1_worst"` / `null`
  detection from header text. Retains `extraction_warnings` requirement.

**Note on default flip impact**: Changing `NUMERIC_SCALE_TO_CEFR` from `1→C1`
(Round 3) to `1→C2` (Round 4) affects all existing `cv_data.json` files that
used the old default for sessions processed with Round 3's `1→C1` mapping. On
reprocessing, those sessions will produce different `*_cefr` values. This is the
correct intended behaviour per the Round 3 production evidence.

---

### R4-E — `references` and `certification_declaration` schema + extraction + context

**Problem**: Round 3 Run 6 — source CV contains a References section (3 named
contacts with full contact details) and a certification declaration block.
Neither field exists in A1's output schema.

**Scope**: `models.py`, `pipeline/agents/cv_extractor.py`, `templates/giz.py`,
`templates/wb.py`.

**Implementation**:

`models.py`:
- `Reference(BaseModel)` class added with optional string fields: `name`,
  `title`, `organisation`, `email`, `phone`.
- `references: list[Reference] = Field(default_factory=list, ...)` added to
  `CVData`. Defaults to `[]`; backward-compatible.
- `certification_declaration: str = Field(default="", ...)` added to `CVData`.
  Defaults to `""`.

`pipeline/agents/cv_extractor.py` (`SYSTEM_PROMPT_A1`):
- `### References` section added: extract named contacts into `Reference` entries
  when a References/Contacts section is present; default to `[]` when absent.
- `### Certification / Declaration` section added: extract the declaration block
  verbatim when present; default to `""` when absent.

`templates/giz.py` and `templates/wb.py` (`_build_context`):
- `"references"` key added (list filtered to entries with non-empty `name`).
- `"certification_declaration"` key added (stripped string).

**Rendering deferred**: Static template inspection confirmed that neither
`GIZ-Template.docx` nor `WB-Template.docx` contains Jinja placeholders for
`references` or `certification_declaration`. Data flows correctly through the
context but produces no visible output until the static templates are edited
to add the corresponding `{% for r in references %}` and
`{{ certification_declaration }}` blocks. This is a one-time manual Word
template edit, tracked in `PIPELINE_DIAGNOSTIC_CONTEXT.md` §5.

---

## Files changed

| File | Change |
|------|--------|
| `pipeline/agents/cv_tor_mapper.py` | `MIN_PROJECTS_TO_KEEP = 3`; `MAX_PROJECTS_TO_KEEP = 10`; `_compute_threshold` returns `0.30 / 0.40 / 0.50`; `_enforce_threshold_and_cap` uses `effective_floor = min(MIN, total)`; `SYSTEM_PROMPT_A3` threshold table updated. |
| `pipeline/agents/fields_generator.py` | `SYSTEM_PROMPT_A4`: new `#### Source preference: condense the candidate's own KQ when bullet-style` subsection. |
| `pipeline/agents/cv_extractor.py` | `map_numeric_scale_inverted` imported; `_apply_cefr_with_direction` helper; `_populate_cefr_fields` direction-aware; `SYSTEM_PROMPT_A1` extended with other_skills routing, numeric scale direction detection, References, and Certification/Declaration sections. |
| `pipeline/utils/cefr.py` | `NUMERIC_SCALE_TO_CEFR` updated to 1_best default; `NUMERIC_SCALE_TO_CEFR_INVERTED` added; `map_numeric_scale_inverted` added; module docstring updated. |
| `models.py` | `from typing import Literal` added; `language_scale_direction` field; `Reference` class; `references` and `certification_declaration` fields on `CVData`. |
| `templates/giz.py` | `_build_context` return dict: `references` and `certification_declaration` keys added. |
| `templates/wb.py` | `_build_context` return dict: `references` and `certification_declaration` keys added. |
| `tests/test_cv_tor_mapper.py` | All threshold parametrize values updated; `test_below_threshold` rewritten for new 0.50 threshold; `test_at_threshold_not_dropped` rewritten; `test_warning_added_when_projects_dropped` scores updated; `TestMinimumGuarantee` rewritten for new floor/threshold; `test_dynamic_floor_clamps_to_total` added; `TestMaximumCap` updated to 12+ projects; `test_run4_simulation` rewritten; `test_prompt_threshold_values_match_python` added. |
| `tests/test_fields_generator_prompt.py` | `TestSystemPromptA4SourcePreference` class with 3 tests added. |
| `tests/test_cv_extractor_prompt.py` | **New file.** 8 tests covering Q routing (3), O scale direction (2), and R extraction sections (2). Also `test_scale_direction_detection_section_present`. |
| `tests/test_cefr_map.py` | `NUMERIC_SCALE_TO_CEFR_INVERTED` and `map_numeric_scale_inverted` imported; `TestNumericScaleMapping` assertions updated to 1_best defaults; `TestInvertedNumericScale` class with 4 tests added; parenthetical-numeric-inner test updated to `"B2"`. |
| `tests/test_cv_extractor_cefr.py` | `test_numeric_raw_in_range_maps_to_cefr` updated to `"B2"`; `test_slash_separated_raw_maps_each_digit` updated to `"B2/B1/B1"`; `test_language_scale_direction_1_worst_inverts` added. |
| `tests/test_models.py` | **New file.** 14 tests for `Reference` model and new `CVData` fields (`language_scale_direction`, `references`, `certification_declaration`). |

---

## Test results

**332/332 tests passing after Round 4.**

---

## Production validation

| Run | CV type | Result | Notes |
|-----|---------|--------|-------|
| R4-Run 3 | GIZ, Dejan Stojadinovic, 44 projects, `page_limit=2` | Partial | R4-A confirmed: 10 projects kept correctly. Compressor ran aggressively — `words_before=1058`, `words_after=534`, `target_words=900` — cutting 524 words. Rendered document still exceeded 2 pages despite compression. Two issues surfaced: Issue S (word target not scaled to page limit) and Issue T (layout-driven overflow, out of pipeline scope). A5 Flag 1: incomplete KQ — source CV contains verbatim placeholder `"More than X years experience as Team Leader"`. A1 extracted faithfully; A5 correctly flagged. Confirmed as source document defect — Issue U. |
| R4-Run 4 | — | Pass | Normal run, acceptable results. No issues. |
| R4-Run 5 | — | Pass | Normal run, acceptable results. No issues. |
| R4-Run 6 | WB format, Rafael Jabba | Partial | A5 Flag 1: `from_date` / `to_date` inconsistency between `employment_record` (Kenya: `11/2020–05/2021`) and `countries_of_experience` (Kenya: `10/2020–06/2021`). Confirmed against source CV — both date sets present verbatim in different source sections. A1 extracted faithfully. Legitimate A5 finding; genuine source inconsistency requiring candidate verification. Closed as expected behaviour. |

---

## Issues surfaced in Round 4 production validation

### Issue S — Compressor word target not scaled to page limit — **PENDING (Fix S)**

**What was observed**: Run 3, `page_limit=2`, GIZ format. Compressor applied
`target_words=900` — the same target used for a 1-page CV — resulting in a 49%
word reduction. The compressor operated correctly against its target; the target
itself is wrong for a 2-page submission. A 2-page GIZ CV should support
approximately 1,400–1,600 words.

**Root cause**: `target_words` is computed without reference to `page_limit`.
The compressor has no awareness that a 2-page CV requires a proportionally higher
word budget.

**Recommended fix**: Introduce `TARGET_WORDS_PER_PAGE` as a per-donor constant
in `pipeline/config.py` (e.g. `GIZ_WORDS_PER_PAGE = 500`,
`WB_WORDS_PER_PAGE = 550`). Compute
`target_words = page_limit * TARGET_WORDS_PER_PAGE` in the orchestrator or
compressor before the compression step. Constants should be calibrated against
real rendered output for each template.

### Issue T — Layout-driven page overflow not reducible by compression — **CLOSED (out of pipeline scope)**

**What was observed**: Run 3 — after compressing to 534 words, the rendered
document still exceeded 2 pages. Page count is driven by fixed structural elements
in the GIZ Word template (tables, section headers, margins, fonts) rather than
prose word count alone.

**Resolution**: Word template layout issue, not a pipeline defect. Closed.

### Issue U — A1 extracts unfilled placeholder text verbatim — **PENDING (R5-E)**

**What was observed**: Run 3 — source CV contains `"More than X years experience
as Team Leader"` where `X` is a literal unfilled placeholder. A1 extracted this
verbatim. A5 correctly flagged it as incomplete.

**Root cause**: A1's prompt has no instruction to detect unfilled placeholders
(standalone uppercase letters in numeric contexts: `X`, `N`, `Y`).

**Recommended fix**: Extend A1's prompt to detect and append an
`extraction_warnings` entry when a likely unfilled placeholder is found
(e.g. `"key_qualifications[3] contains likely unfilled placeholder: 'More than
X years experience as Team Leader'.")`. A1 still extracts the text faithfully;
the warning surfaces it for human review. No schema changes required.

---

## Markdowns updated

`PIPELINE_DIAGNOSTIC_CONTEXT.md`, `PIPELINE_DIAGNOSTIC_ROUND_4.md` (this file),
`PROMPT_REVIEW_CONTEXT.md`, `PROMPT_REVIEW_IMPLEMENTATION.md`,
`PIPELINE_CONTEXT.md`, `RUNS_ARTIFACTS_CONTEXT.md`.

---

## Design decisions recorded

**R4-A dynamic floor**: `effective_floor = min(MIN_PROJECTS_TO_KEEP, len(scores))`
computed inside `_enforce_threshold_and_cap` rather than making `MIN_PROJECTS_TO_KEEP`
a function. Keeps the constant semantics clean; the clamp is an internal guard.

**R4-B default flip**: `NUMERIC_SCALE_TO_CEFR` changed from `1→C1` (Fix M Part 1
default; Round 3 interim) to `1→C2` (1_best default). This is the dominant convention in
development-sector CVs per Round 3 Run 4 evidence. Sessions reprocessed after
this change will produce different `*_cefr` values for numeric-scale inputs.

**R4-B field placement**: `language_scale_direction` placed at the top level of
`CVData` (not inside `LanguageProficiency`) — matches the diagnostic doc's framing
and reflects the practical reality that one consistent scale convention applies
per source document.

**R4-E rendering gap**: Static `.docx` templates confirmed (via `python-docx`
inspection) to have no `references` or `certification_declaration` placeholders.
Data flow implemented; rendering deferred to a manual one-time template edit.
Documented in `PIPELINE_DIAGNOSTIC_CONTEXT.md` §5 ("What this document does not
cover").

**R5-B, R5-C, R5-D scope reduction**: These three items appear in the Round 4
per-round file as "Planned fixes" but are deferred to Round 5. R5-B depends on
R4-A being validated in production first. R5-C depends on R4-A validation for
the same reason (upgrading model and constants simultaneously obscures regression
attribution). R5-D (soft-flag validators) is low urgency and implement-last.

**A2 keyword extraction for R5-B scoring (R5-A)**: During Round 4 production
review, an extension to R5-B was identified and agreed. A2 (ToR Summarizer)
should be extended to emit a `scoring_keywords` block containing three keyword
sets derived from the ToR: `role_implied` (keywords implied by the position
title that may not appear explicitly in the ToR body), `scope_implied` (thematic
areas and intervention types described in the project scope), and `explicit`
(directly stated requirements such as geography, years of experience, sector).
These keywords feed into R5-B's Python keyword overlap scoring (35% weight)
as a richer, more ToR-faithful signal than what can be inferred from tasks alone.
The keyword set would be written to `tor_data.json` and visible for audit —
making the scoring basis transparent and explainable. This is a light generative
inference step (role-implied keywords require A2 to reason beyond extraction),
which pairs with R5-C (A2 upgrade to Sonnet). R5-B and R5-C should therefore
land in the same round. Documented as R5-A; to be incorporated into
`RELEVANCE_SCORING_DESIGN.md` before Round 5 implementation.

**Compressor word target (Issue S)**: Agreed fix approach is Option 1 —
page-limit-aware word target. `TARGET_WORDS_PER_PAGE` introduced as a per-donor
constant in `pipeline/config.py`; `target_words` computed as
`page_limit * TARGET_WORDS_PER_PAGE` before the compression step. Constants to
be calibrated per template against real rendered output.
