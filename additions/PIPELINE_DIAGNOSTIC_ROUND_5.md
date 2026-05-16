# Pipeline Diagnostic — Round 5 Implementation Record

**Date**: May 2026
**Status**: Complete
**Tests after round**: 393/393 passing

---

## Fixes delivered

### Fix U — A1 unfilled placeholder detection

**Problem**: Round 4 Run 3 — source CV contains `"More than X years experience as
Team Leader"` where `X` is a literal unfilled placeholder. A1 extracted it verbatim.
A5 correctly flagged it as incomplete. No extraction-time warning existed.

**Scope**: `SYSTEM_PROMPT_A1` in `pipeline/agents/cv_extractor.py`. Prompt-only change.

**Implementation**: Added `### Unfilled placeholder detection` subsection under
`### Strictness`. A1 still extracts text faithfully but appends an
`extraction_warnings` entry of the form:
`"<field_path> contains likely unfilled placeholder: '<verbatim text>'"`.
Common patterns documented: standalone uppercase letter in numeric context
(`X years`, `N people`), bracket-delimited gaps (`[YEARS]`, `{n}`), underscore
gaps (`__ years`). Explicit exclusion of intentional uses (X-ray, HIV/AIDS, etc.).

---

### Fix 2 — Upgrade all remaining agents to Sonnet

**Problem**: A1–A3, A5, A6 still used Haiku (`ANTHROPIC_MODEL`). A2's role-implied
keyword inference (Fix 4b) requires Sonnet-quality reasoning. A3 and A5 also
benefit from Sonnet's stronger reasoning for scoring and review tasks.

**Scope**: Single constant in `pipeline/config.py`.

**Implementation**: `ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"` (was
`"claude-haiku-4-5-20251001"`). All five agents (A1, A2, A3, A5, A6) automatically
pick up the change at their `model=ANTHROPIC_MODEL` call sites. Agent 4 retains its
separate `ANTHROPIC_SYNTHESIS_MODEL` constant (unchanged). Field editor retains its
own `MODEL` constant (unchanged).

---

### Fix 4b — A2 `scoring_keywords` extraction

**Problem**: Fix 4's Python relevance scorer needed a richer keyword set than what
`sector_keywords` alone provides. The position title implies technical vocabulary
that often does not appear in the tasks list. A2 on Sonnet can infer this.

**Scope**: `models.py` (new `ScoringKeywords` model + `DistilledToR.scoring_keywords`
field) and `SYSTEM_PROMPT_A2` in `pipeline/agents/tor_summarizer.py`.

**Implementation**:

`models.py`:
- `ScoringKeywords(BaseModel)` class with three `list[str]` fields:
  `role_implied`, `scope_implied`, `explicit`.
- `DistilledToR.scoring_keywords: ScoringKeywords = Field(default_factory=ScoringKeywords, ...)`
  added with backward-compatible `default_factory`.

`SYSTEM_PROMPT_A2`:
- New `### Scoring keywords` section documenting all three lists.
- `role_implied`: infer from position title and pool name (Sonnet-level reasoning).
- `scope_implied`: extract from project scope / background section.
- `explicit`: directly stated requirements (geography, years, sector).
- Quantity guidance: 5–15 keywords per list; prefer specific technical terms.

---

### Fix 4 — Python relevance scoring for Agent 3 + duration upstream

**Problem**: A3's scoring was entirely LLM-side and inconsistent. The
`_precompute_relevance_scores` stub returned `None`. A3's LLM scored projects with no
`duration` field populated (the pre-compute ran inside `fields_generator.py`, after A3).

**Scope**: `pipeline/precompute_utils.py` (new helpers), `pipeline/agents/cv_tor_mapper.py`
(stub replaced; duration pre-compute added; A3 prompt updated),
`pipeline/agents/fields_generator.py` (pre-compute call removed — now upstream).

**Implementation**:

`pipeline/precompute_utils.py`:
- `keyword_overlap_score(project, keywords) -> (float, list[str])` — case-insensitive
  substring match across `main_project_features`, `activities_performed`,
  `positions_held`, `project_name`.
- `geography_score(project, required_countries) -> (float, list[str])` — exact match = 1.0;
  regional word overlap (>4 chars) = 0.5; no match = 0.0.
- `compute_composite_score(kw_score, geo_score, kw_weight=0.35, geo_weight=0.15) -> float`
  — 50% Python-computed; remaining 50% (tasks/competencies) adjusted by LLM ±0.10.

`pipeline/agents/cv_tor_mapper.py`:
- `_precompute_project_dates_for_mapper(cv_data)` — equivalent to the old A4 helper,
  now lives in A3's file.
- `_precompute_relevance_scores(cv_data, tor_data)` — real implementation: consumes
  `scoring_keywords` (merged all three lists); falls back to legacy `sector_keywords`
  when `scoring_keywords` absent; returns structured `project_scores` dict.
- `run()`: calls `_precompute_project_dates_for_mapper(cv_data)` before scoring.
- `SYSTEM_PROMPT_A3`: new `## Pre-computed scores` section instructs LLM to start
  from `composite_score` and adjust ±0.10 for semantic alignment.

`pipeline/agents/fields_generator.py`:
- `_precompute_project_dates` call in `run()` replaced with a comment noting the
  upstream move. Helper itself retained (still tested for backward compatibility).

---

### Fix 5b — Soft-flag manifest warnings

**Problem**: Remaining semantic validation gaps: A5→A6 review block check,
A6→renderer compression block check. Also quality-concern flags for high
generation_warnings counts and partial empty generated_fields.

**Scope**: `pipeline/manifest.py` (new `append_warning`), `pipeline/validators.py`
(three new check functions), `pipeline/orchestrator.py` (wired in phase 3).

**Implementation**:

`pipeline/manifest.py`:
- `append_warning(run_dir, stage, kind, message, details=None)` — appends a
  soft-flag entry to `manifest.json["warnings"]` (creates key if absent).
  Thread-safe via `manifest_lock`.

`pipeline/validators.py`:
- `check_fields_generator_warnings(run_dir)` — flags if `generation_warnings` count
  > 3 or if any (not all) `generated_fields[].content` is empty (partial failure).
- `check_content_reviewer_warnings(run_dir)` — flags if `review` block is null
  or `high_severity` count > 5.
- `check_compressor_warnings(run_dir)` — flags if `compression` block is null,
  `applied=false`, `target_not_reached=true`, or `words_after < 200`.

`pipeline/orchestrator.py`:
- `run_phase3`: soft-flag check loops added after A4 and A5 runs.
- `_run_compressor_and_halt`: soft-flag check loop added after A6 runs.
- All checks call `append_warning(run_dir, **w)` for each returned warning entry.
- None of the checks raise — pipeline always continues.

`manifest.json` gains a `"warnings": []` key visible via `GET /sessions/{id}/manifest`.
No router change required (manifest is already returned verbatim).

---

## Files changed

| File | Change |
|------|--------|
| `pipeline/config.py` | `ANTHROPIC_MODEL` → `claude-sonnet-4-20250514` (Fix 2) |
| `pipeline/agents/cv_extractor.py` | `SYSTEM_PROMPT_A1`: `### Unfilled placeholder detection` section (Fix U) |
| `pipeline/agents/tor_summarizer.py` | `SYSTEM_PROMPT_A2`: `### Scoring keywords` section (Fix 4b) |
| `pipeline/agents/cv_tor_mapper.py` | `_precompute_project_dates_for_mapper`; `_precompute_relevance_scores` real impl; `run()` upstream duration + scoring; `SYSTEM_PROMPT_A3` pre-computed scores section. New imports from `precompute_utils`. (Fix 4 + Fix 4b) |
| `pipeline/agents/fields_generator.py` | Remove `_precompute_project_dates` call from `run()` (moved upstream). Comment explains. (Fix 4) |
| `pipeline/manifest.py` | `append_warning` helper (Fix 5b) |
| `pipeline/orchestrator.py` | Import `append_warning` and 3 check functions; wire soft-flag loops in `run_phase3` and `_run_compressor_and_halt` (Fix 5b) |
| `pipeline/precompute_utils.py` | `keyword_overlap_score`, `geography_score`, `compute_composite_score` (Fix 4); module docstring updated |
| `pipeline/validators.py` | `check_fields_generator_warnings`, `check_content_reviewer_warnings`, `check_compressor_warnings` (Fix 5b); module docstring updated |
| `models.py` | `ScoringKeywords` class; `DistilledToR.scoring_keywords` field (Fix 4b) |
| `tests/test_cv_extractor_prompt.py` | `TestSystemPromptA1UnfilledPlaceholder` — 3 tests (Fix U) |
| `tests/test_tor_summarizer_prompt.py` | **New file.** `TestSystemPromptA2ScoringKeywords` — 4 tests (Fix 4b) |
| `tests/test_models.py` | `TestScoringKeywordsModel` + `TestDistilledToRScoringKeywords` — 7 tests (Fix 4b) |
| `tests/test_precompute_utils.py` | `TestKeywordOverlapScore`, `TestGeographyScore`, `TestComputeCompositeScore` — ~20 tests (Fix 4) |
| `tests/test_cv_tor_mapper.py` | `TestPrecomputeRelevanceScores`, `TestDurationUpstreamPrecompute` — ~9 tests; cap tests updated for current `MAX_PROJECTS_TO_KEEP=15` (Fix 4) |
| `tests/test_fields_generator_precompute.py` | Module docstring updated to note upstream move |
| `tests/test_validators.py` | `TestCheckFieldsGeneratorWarnings`, `TestCheckContentReviewerWarnings`, `TestCheckCompressorWarnings` — 18 tests (Fix 5b) |
| `tests/test_manifest_warnings.py` | **New file.** `TestAppendWarning` — 5 tests (Fix 5b) |

---

## Test results

**393/393 tests passing after Round 5.**

---

## Production validation

| Run | CV type | Result | Notes |
|-----|---------|--------|-------|
| R5-Run 1 | — | Pass | Normal run. No issues. |
| R5-Run 2 | — | Pass | Normal run. No issues. |
| R5-Run 3 | — | Pass | Normal run. Occasional project dropping noted — planned for fine-tuning alongside compressor behaviour. |
| R5-Run 4 | GIZ, Merita Kostari, 24 projects, PDF ToR | Partial | Three critical issues surfaced. (1) 11 of 24 projects extracted with blank `project_name` and empty detail fields — A1 failed to extract from merged-cell two-column CV table layout (Issue V). (2) `countries_of_experience` `date_from`/`date_to` inverted throughout — end date placed in `date_from` (Issue W). (3) Empty bullet placeholders appeared in text extraction but confirmed absent in actual rendered Word document — closed as false positive (Issue X). Additionally, `tor_data.json` confirmed `scoring_keywords` entirely empty despite rich PDF ToR content — Fix 4b prompt failure on PDF input (Issue Y). Scores near-uniform (0.20–0.28) with only geography providing signal. |
| R5-Run 5 | GIZ, Jennifer Garvey, 12 projects, PDF ToR | Pass | `scoring_keywords` fully populated across all three pools — Fix 4b confirmed working on this ToR. All 12 project names correctly extracted, no blank entries. `countries_of_experience` empty (0 entries) — A1 extraction miss for this candidate's CV format, distinct from Issue W. 5 of 12 projects kept (floor at MIN=5); scores uniformly low (0.02–0.25) reflecting genuine candidate-ToR mismatch (Mozambique/US-based lawyer vs South Africa power sector ToR). 4 KQs generated and ToR-aligned. Compression not applied (854 words vs 1800 target). Issue X confirmed closed — no empty bullets in rendered output. |
| R5-Run 6 | WB format, Rafael Jabba, PDF ToR, `page_limit=4` | Failed | Compressor hard failure: `"Expecting ',' delimiter: line 403 column 171 (char 14574)"`. A6 LLM response truncated mid-JSON. Root cause: 1,696 words of `activities_performed` across 5 projects (first project: 694 words) exceeded A6's effective output budget. Fix 8 Part 3 caps A4's input but A4 expanded content in output; Fix M Part 2 correctly restored originals — A6 received full untruncated volume with no equivalent cap. Additionally, `detailed_tasks` was empty (0 entries) despite WB format — A4 minimum output guarantee did not fire for `detailed_tasks` on geographic mismatch (The Gambia). Issues Z and AA surfaced. |

---

## Issues surfaced in Round 5 production validation

### Issue V — A1 fails to extract `project_name` and project details from merged-cell table layout — **PENDING (Fix V)**

**What was observed**: Run 4 — 11 of 24 projects in `cv_data.json` had empty
`project_name` and empty detail fields (`activities_performed`, `positions_held`,
etc.). Only 1 project had a populated name. Confirmed against source CV
(`CV-eng_Merita_Kostari-original.docx`): the CV uses a two-column table where
the left column contains the project title merged with dates and the right column
contains the description. A1 correctly created 24 project entries but failed to
map the left column content to `project_name`, leaving it blank for all
merged-cell rows.

**Root cause**: A1's prompt does not explicitly instruct it to extract `project_name`
from the left column of a two-column project table, particularly when cells are
merged. Standard extraction logic misses the title when it appears in a merged
cell alongside dates.

**Recommended fix**: Extend A1's prompt to explicitly handle two-column project
table layouts — instruct it to extract `project_name` from the left/title column
regardless of cell merge formatting, treating the first substantive text in that
column (excluding dates) as the project name.

---

### Issue W — A1 inverts `date_from` / `date_to` for `countries_of_experience` — **PENDING (Fix W)**

**What was observed**: Run 4 — all `countries_of_experience` entries had
`date_from` and `date_to` swapped. Example: "Kosovo | January 2021 - August 2019"
rendered in the output document (end date before start date). Confirmed in
`mapped_cv.json` — the inversion originates at A1 extraction time.

**Root cause**: A1 is populating `date_from` with the end date and `date_to` with
the start date for this specific section. Likely a prompt ambiguity — the field
names are the same as in `relevant_projects` but A1 may be reading the table
in the wrong column order for `countries_of_experience`.

**Recommended fix**: Extend A1's prompt to explicitly validate date ordering for
`countries_of_experience` entries — `date_from` must be chronologically earlier
than `date_to`. Add an `extraction_warnings` entry when a date inversion is
detected and auto-correct the swap.

---

### Issue X — Renderer writes empty bullet placeholders when `other_relevant_info` and `publications` are both empty — **PENDING (Fix X)**

**What was observed**: Run 4 — three empty bullet points (`- ** ** -`) rendered
in the "Other relevant information" section of the output document. Both
`other_relevant_info` and `publications` were empty in `generated_fields.json`.
The renderer fires the bullet template unconditionally.

**Root cause**: The GIZ renderer does not check whether `other_relevant_info`
and `publications` are empty before rendering the section. The template produces
empty bullets rather than omitting the section.

**Recommended fix**: Add a conditional check in the GIZ renderer's `_build_context`
(or in the Jinja template) — only render the "Other relevant information" section
when at least one of `other_relevant_info` or `publications` is non-empty.

---

### Issue Y — A2 produces empty `scoring_keywords` despite rich ToR content — **PENDING (Fix Y)**

**What was observed**: Run 4 — `tor_data.json` showed `scoring_keywords.role_implied`,
`scope_implied`, and `explicit` all as empty lists `[]`. The ToR (a 36-page PDF)
contains explicit position requirements, work package descriptions, and country
requirements sufficient to populate all three lists. Consequence: Fix 4's Python
keyword scorer had no keywords to match against, producing near-uniform scores
(0.20–0.28) driven almost entirely by geography match and LLM adjustment.

**Root cause**: Two possible causes requiring investigation: (1) A2's
`### Scoring keywords` prompt section is not firing correctly for PDF-sourced
ToR content — the PDF text may arrive in a format that A2 does not parse
correctly for keyword extraction; (2) the Sonnet model is skipping the section
when the ToR is long (36 pages), hitting context or attention limits before
reaching the keyword extraction instruction.

**Recommended fix**: (1) Verify PDF text reaches A2 intact by checking
`tor_data.json` for other correctly extracted fields — if tasks and pools are
correct, the PDF parsing is fine and the issue is purely prompt; (2) Move the
`### Scoring keywords` extraction instruction earlier in `SYSTEM_PROMPT_A2` so
it is not deprioritised on long inputs; (3) Add a `generation_warnings` entry
to `tor_data.json` when all three keyword lists are empty, so the soft-flag
validator (Fix 5b) can surface this to the user.

---

### Issue X — Renderer empty bullet placeholders — **CLOSED (false positive)**

Text extraction showed empty bullet markup in "Other relevant information".
Confirmed absent in actual rendered Word documents for Runs 4 and 5. The
placeholder markup exists in template XML but does not render visibly in Word.
Closed as a false positive from the text extraction tool.

---

### Issue Z — Compressor JSON truncation on large input — **PENDING (Fix Z)**

**What was observed**: Run 6 — compressor failed with JSON parse error at
character 14,574. A6's LLM response was truncated mid-JSON. 1,696 words of
`activities_performed` across 5 projects (first: 694 words) exceeded A6's
effective output budget on a 4-page WB CV.

**Root cause**: Fix 8 Part 3 caps A4's input to 150 words per project, but A4
can expand content in its output. Fix M Part 2 correctly restores originals into
`generated_fields.json`. A6 therefore receives the full untruncated volume with
no equivalent cap of its own.

**Recommended fix**: Apply a word cap to A6's input assembly, mirroring Fix 8
Part 3's pattern. Truncate `activities_performed` in A6's input only; preserve
originals for the artifact write.

---

### Issue AA — A4 `detailed_tasks` empty on geographic mismatch (WB format) — **PENDING (Fix AA)**

**What was observed**: Run 6 — WB format with `detailed_tasks` in
`generative_field_keys`. A4 produced 0 entries despite Fix 8 Part 2's minimum
output guarantee. Generation warning: "No geographic alignment with ToR location
(The Gambia)."

**Root cause**: Minimum output guarantee in `SYSTEM_PROMPT_A4` may be scoped to
`key_qualifications` only, not all `generative_field_keys` entries.

**Recommended fix**: Update the guarantee to explicitly cover all
`generative_field_keys` entries — for WB format, `detailed_tasks` must always
have at least one entry regardless of alignment strength.

---

## Markdowns updated

`PIPELINE_DIAGNOSTIC_CONTEXT.md`, `PIPELINE_DIAGNOSTIC_ROUND_5.md` (this file),
`RELEVANCE_SCORING_DESIGN.md`, `PROMPT_REVIEW_CONTEXT.md`,
`PROMPT_REVIEW_IMPLEMENTATION.md`, `PIPELINE_CONTEXT.md`,
`RUNS_ARTIFACTS_CONTEXT.md`.

---

## Design decisions recorded

**Fix 2 full sweep**: A1/A2/A3/A5/A6 all upgraded to Sonnet via the single
`ANTHROPIC_MODEL` constant. The primary driver is A2's role-implied keyword
inference (Fix 4b), which requires Sonnet-quality reasoning. A3 and A5 are
secondary beneficiaries. Field editor and A4 retain their independent constants.

**Fix 4 keyword merging**: All three `scoring_keywords` lists (`role_implied`,
`scope_implied`, `explicit`) are merged into a single list for `_keyword_score`.
No weighting differential between the three lists at the merge stage — the
composite formula (`0.35` keyword weight overall) is the control.

**Fix 4 fallback**: When `tor_data["scoring_keywords"]` is absent (old sessions),
`_precompute_relevance_scores` falls back to `tor_data["sector_keywords"]`. If
both are absent, it returns `None` — legacy A3 LLM-only scoring applies.

**Fix 4 duration upstream move**: `_precompute_project_dates` call removed from
`fields_generator.run()` and its equivalent added to `cv_tor_mapper.run()`. The
helper itself stays in `fields_generator.py` for backward-compatible tests. The
move is a call-site change only; the algorithm is identical.

**Fix 5b scope**: Soft flags only (non-blocking). Hard blocks for null review and
compression blocks were discussed and rejected in favour of soft flags — null
blocks are possible in unusual edge cases (e.g. reviewer blocked) and halting on
them would create false negatives. The existing Fix 5a hard-block on
all-empty generated_fields remains the only hard stop.

**Fix S deferred**: `COMPRESSION_CALIBRATION_CONTEXT.md` requires 5+ clean
rendered `.docx` outputs across GIZ and WB templates at varying page limits.
This data is not yet available. The code infrastructure (`words_to_target` in
both renderers) already exists. Fix S is one constant-calibration step away.

**Code-vs-doc drift (`MIN/MAX_PROJECTS_TO_KEEP`)**: Round 4 per-round file
records `MIN=3, MAX=10`. Current code values are `MIN=5, MAX=15`, reflecting
post-Round-4 production tweaks. The Round 4 file is a historical record and
not updated. Current code values treated as ground truth. These will be
formally reviewed in Round 6 once Fix 4 scoring provides a stable distribution.
