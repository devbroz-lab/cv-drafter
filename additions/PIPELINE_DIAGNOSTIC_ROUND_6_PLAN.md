# Pipeline Diagnostic — Round 6 Implementation Plan

**Date**: May 2026
**Status**: ✓ Implemented (re-implementation — A1 prompt restructure + model upgrade)
**Baseline tests**: 426/426 passing (post-Round 6 first attempt)
**Tests after re-implementation**: 426/426 passing

---

## Re-implementation note

The initial Round 6 attempt (Fix Z, AA, V, W, Y) was executed and tests pass
(426/426). However A1 continued to fail to populate project details in
production runs. Root cause analysis identified two issues:

1. `claude-sonnet-4-20250514` is **deprecated** (retiring June 15, 2026) and
   has only a 200k token context window. The full rendered A1 system prompt
   (schema + extraction rules) is ~35k chars; with a dense CV user message this
   approaches the limit, causing the LLM to de-prioritise or skip instructions.

2. `SYSTEM_PROMPT_A1` had grown to 14,365 chars (2,040 words pre-schema) with
   contradictory employment-fallback rules in two places and an incorrect field
   mapping (`employer → company` vs the correct `employer → project_name`).

This re-implementation fixes both root causes with minimal, targeted changes.

---

---

## Scope

Five fixes from `PIPELINE_DIAGNOSTIC_ROUND_6.md`. Fix S and Fix 4 threshold
recalibration explicitly deferred to Round 7.

| Step | Fix | Priority | Files |
|------|-----|----------|-------|
| 1 | **Fix Z** | Highest — hard failure (compressor JSON truncation) | `compressor.py`, `validators.py`, `orchestrator.py`, new `test_compressor_text_cap.py`, extended `test_validators.py` |
| 2 | **Fix AA** | High — silent WB quality failure | `fields_generator.py` (`SYSTEM_PROMPT_A4`), extended `test_fields_generator_prompt.py` |
| 3 | **Fix V** | Medium — quality | `cv_extractor.py` (`SYSTEM_PROMPT_A1`), extended `test_cv_extractor_prompt.py` |
| 4 | **Fix W** | Medium — quality | `cv_extractor.py` (`SYSTEM_PROMPT_A1`), extended `test_cv_extractor_prompt.py` |
| 5 | **Fix Y** | Medium — quality | `tor_summarizer.py` (`SYSTEM_PROMPT_A2`), `validators.py`, `orchestrator.py`, extended `test_tor_summarizer_prompt.py`, extended `test_validators.py` |
| 6 | **Markdown updates** | Documentation | 6 files including per-round record and master diagnostic cleanup |

---

## Decisions confirmed by user

| # | Decision |
|---|----------|
| 1 | **Fix Z** — truncate-and-warn. Mirror Fix 8 Part 3 pattern for A6. Information beyond word 150 per dense field is dropped from compression scope. Soft-flag manifest warning surfaces every truncation event. No merge/restore step (A6 is supposed to change these fields). Simplest implementation: `append_warning` called directly from `compressor.run()` rather than a transient JSON file + validator. |
| 2 | **Fix AA** — targeted reinforcement only. Keep existing guarantee language; add a bullet naming `detailed_tasks` explicitly and a sentence stating geographic/alignment weakness does not exempt any key. |
| 3 | **Fix V** — leave `project_name = ""` when not determinable + emit `extraction_warnings` entry. No fabrication. |
| 4 | **Fix W** — apply date inversion check and auto-correct to **all** `date_from`/`date_to` pairs (`relevant_projects[]`, `education[]`, `employment_record[]`, `countries_of_experience[]`). Swap + flag in `extraction_warnings` for each corrected pair. "Present" always sorts later than any literal date. |
| 5 | **Fix Y** — new `check_tor_summarizer_warnings` function in `pipeline/validators.py`; wired in `run_phase1` after `tor_summarizer.run`. |

---

## Step-by-step implementation detail

---

### Step 1 — Fix Z: A6 input word cap

**Problem**: Run 6 Round 5 — compressor hard failure. A6 received 1,696 words of
`activities_performed` across 5 projects (first project alone: 694 words). A6's LLM
response was truncated mid-JSON, producing `"Expecting ',' delimiter: line 403 column
171"`. Fix 8 Part 3 caps A4's input but A4 may expand content in its output; Fix M
Part 2 restores originals for A4 — so A6 sees the full untruncated volume with no
equivalent cap.

**Root cause**: No per-project word cap on the `cv_data` passed into A6's user
message. A single project with 694 words of `activities_performed` can exhaust A6's
effective output budget.

**Key difference from Fix 8 Part 3 (A4)**: A6 is *supposed to shorten* these
fields. There is no restoration step. Information beyond word 150 per field is
permanently dropped from the compressor's output. The soft-flag warning surfaces
this loss to the user.

**Implementation — `pipeline/agents/compressor.py`**:

1. Add constants near top of file (after existing constants):
   ```python
   A6_INPUT_PROJECT_WORD_CAP: int = 150
   _A6_CAPPED_FIELDS: tuple[str, ...] = ("activities_performed", "main_project_features")
   ```

2. Add helper function before `run()`:
   ```python
   def _truncate_project_text_for_a6(cv_data: dict) -> tuple[dict, list[dict]]:
       """
       Return (truncated_cv_data, truncation_events).

       truncated_cv_data: deep copy with activities_performed and
       main_project_features capped to A6_INPUT_PROJECT_WORD_CAP per project.
       Text beyond the cap is dropped (unlike Fix 8 Part 3 for A4, there is
       no restoration — A6 is expected to compress these fields anyway).
       Truncated text is suffixed with "…" (U+2026).

       truncation_events: list of dicts recording each truncation:
         [{"project_name": str, "field": str,
           "original_word_count": int, "truncated_word_count": int}, ...]
       Empty when no field exceeded the cap.
       """
   ```

3. In `run()`, call immediately before user_message assembly (after
   line 246 `resolve_tor_for_agents`):
   ```python
   # Fix Z: cap project text in A6's input to prevent JSON truncation on
   # dense CVs. Unlike Fix 8 Part 3 (A4), no restoration is needed because
   # A6 is explicitly compressing these fields. Information beyond cap is
   # intentionally excluded from the compression scope.
   cv_data_a6_input, truncation_events = _truncate_project_text_for_a6(cv_data_in)

   # Recompute word counts on the truncated input — target arithmetic must
   # be based on what A6 actually sees.
   words_per_field = count_words_per_field(cv_data_a6_input)
   current_words = sum(words_per_field.values())
   ```

   Replace `cv_data_in` with `cv_data_a6_input` in the user_message construction.

4. After `_run_compressor_and_halt` or at the end of the compression block,
   call `append_warning` for each truncation event:
   ```python
   # Emit soft-flag warnings for any fields truncated before A6 compression.
   for evt in truncation_events:
       append_warning(
           run_dir,
           stage="compressor",
           kind="input_field_truncated",
           message=(
               f"Project '{evt['project_name']}' field '{evt['field']}' was "
               f"truncated from {evt['original_word_count']} to "
               f"{evt['truncated_word_count']} words before A6 compression. "
               f"Content beyond {A6_INPUT_PROJECT_WORD_CAP} words was excluded "
               f"from compression scope."
           ),
           details=evt,
       )
   ```

   Note: `append_warning` is already imported in `compressor.py`? Not yet — it
   will need to be imported: `from pipeline.manifest import append_warning`.

**`tests/test_compressor_text_cap.py`** (new file, ~12 tests):
- Mirror structure of `tests/test_fields_generator_text_cap.py`.
- `TestTruncateProjectTextForA6`:
  - `test_over_cap_activities_truncated`
  - `test_main_project_features_truncated`
  - `test_exactly_at_cap_not_truncated`
  - `test_under_cap_unchanged`
  - `test_empty_field_unchanged`
  - `test_ellipsis_appended_u2026`
  - `test_original_not_mutated`
  - `test_truncation_events_populated`
  - `test_no_events_when_under_cap`
  - `test_events_shape` (project_name, field, original_word_count, truncated_word_count)
  - `test_both_fields_truncated_independently`
  - `test_multiple_projects_all_processed`

---

### Step 2 — Fix AA: A4 minimum output guarantee for all `generative_field_keys`

**Problem**: Round 5 Run 6 — WB format, A4 produced 0 `detailed_tasks` entries
despite Fix 8 Part 2's minimum guarantee. Fix 8 Part 2 text says "at least one
GeneratedField entry per key in generative_field_keys" but does not name `detailed_tasks`
explicitly. Geographic mismatch (The Gambia) caused A4 to interpret the guarantee as
not applying.

**Root cause**: Minimum output guarantee text is abstract. When A4 has a strong
reason to believe it should produce nothing (geographic mismatch), it apparently
reads the guarantee as aspirational for cases where *some* alignment exists.

**Implementation — `pipeline/agents/fields_generator.py`** (`SYSTEM_PROMPT_A4`):

In the existing `### Minimum output guarantee` subsection, after the bullet point
about not setting `content` to `""`, add:

```
**This guarantee applies to ALL keys in `generative_field_keys`, regardless
of format or alignment:**
- GIZ runs: `key_qualifications` — at least one entry.
- WB runs: `detailed_tasks` — at least one entry.

Geographic mismatch, sector mismatch, or any alignment weakness does NOT
exempt you from generating at least one entry for each key. If the candidate
has no experience in The Gambia but the ToR requires it, you still produce at
least one `detailed_tasks` entry grounded in the candidate's closest available
experience, flagged via `generation_warnings`:
  `"Low-confidence detailed_tasks entry: No geographic alignment with ToR
  (required: The Gambia); used closest available project."`.

Returning an empty list for any `generative_field_keys` key — including
`detailed_tasks` — causes the pipeline to halt at the post-A4 validator.
A weak but honest entry is always preferable to a halt.
```

**`tests/test_fields_generator_prompt.py`** — extend `TestSystemPromptA4MinimumOutputGuarantee`:
- `test_detailed_tasks_explicitly_mentioned` — asserts `detailed_tasks` appears in the guarantee section.
- `test_geographic_mismatch_does_not_exempt` — asserts the prompt explicitly states geographic/alignment weakness is not an exemption.

---

### Step 3 — Fix V: A1 project_name from merged-cell tables

**Problem**: Round 5 Run 4 — 11 of 24 projects had blank `project_name` and empty
detail fields. Source CV uses a two-column table with merged cells where the left
column contains project title and dates.

**Implementation — `pipeline/agents/cv_extractor.py`** (`SYSTEM_PROMPT_A1`):

Add a new subsection `### Merged-cell and two-column project tables` after the
GIZ/WB format-specific rules (around line 118):

```
### Merged-cell and two-column project tables

Some CVs present project experience in a two-column table where:
- The **left column** contains the project title merged with date ranges in a
  single cell spanning multiple visual rows.
- The **right column** provides the project body (activities, client, etc.).

When you encounter this layout:
- Treat the first substantive non-date text in the left column as `project_name`.
- Treat date strings in the same left-column cell as `date_from` / `date_to`.
- Map right-column content to the appropriate project body fields.

If you genuinely cannot identify `project_name` from the left column
(e.g. the cell contains only dates, is blank, or the layout is ambiguous),
leave `project_name = ""` AND append an `extraction_warnings` entry:
  `"relevant_projects[N].project_name could not be determined from source
  table layout (merged-cell or missing title)."`

Do NOT fabricate a project name. An empty `project_name` with a warning is
the correct output for ambiguous layouts.
```

**`tests/test_cv_extractor_prompt.py`** — add `TestSystemPromptA1MergedCellExtraction`:
- `test_merged_cell_project_section_present`
- `test_left_column_extraction_rule_documented`
- `test_project_name_extraction_warning_documented`

---

### Step 4 — Fix W: A1 date inversion auto-correct

**Problem**: Round 5 Run 4 — all `countries_of_experience` entries had `date_from`
and `date_to` swapped.

**Implementation — `pipeline/agents/cv_extractor.py`** (`SYSTEM_PROMPT_A1`):

Add a new subsection `### Date ordering validation` after `### Date normalisation`
(around line 125):

```
### Date ordering validation

After extracting all date_from / date_to pairs, validate ordering across ALL
fields that use them:
- `relevant_projects[]` (date_from, date_to)
- `education[]` (date_from, date_to)
- `employment_record[]` (from_date, to_date)
- `countries_of_experience[]` (date_from, date_to)

**Ordering rule**: `date_from` must be chronologically earlier than or equal
to `date_to`. "Present" / "current" / "to date" always sorts LATER than any
literal date — a pair with `date_to = "Present"` is always correctly ordered.

**When an inversion is detected**:
1. Swap `date_from` and `date_to` in the output.
2. Append an `extraction_warnings` entry of the form:
   `"<field_path>[N] date_from/date_to inverted at source; swapped during
   extraction. Original: date_from='<X>', date_to='<Y>'."`
   For example:
   `"countries_of_experience[2] date_from/date_to inverted at source; swapped
   during extraction. Original: date_from='2020', date_to='2015'."`

This corrects transcription errors in the source document while making the
correction fully visible via extraction_warnings for human verification.
```

**`tests/test_cv_extractor_prompt.py`** — add `TestSystemPromptA1DateOrdering`:
- `test_date_ordering_section_present`
- `test_swap_rule_documented`
- `test_all_four_date_fields_covered` — asserts `relevant_projects`, `education`, `employment_record`, `countries_of_experience` are all named.

---

### Step 5 — Fix Y: A2 scoring_keywords prompt fix + soft-flag

**Problem**: Round 5 Run 4 (PDF ToR, 36 pages) — all three `scoring_keywords` lists
empty. Fix 4b confirmed working on non-PDF ToR in Run 5. Root cause: scoring_keywords
section deprioritised on long PDF inputs because it currently appears last in A2's
extraction rules.

#### 5a — Reorder + strengthen `SYSTEM_PROMPT_A2`

Move `### scoring_keywords` from its current last position (line 130 in
`tor_summarizer.py`) to **immediately after `### position_title`** (after line 64).
Rationale: `role_implied` depends on position_title; placing scoring_keywords
adjacent reinforces that the position title is the primary inference source.

Strengthen the non-empty guarantee by adding at the end of the scoring_keywords
section:

```
**Non-empty guarantee**: For any non-empty ToR input, at least one of the
three keyword lists must be populated. Even on long PDF inputs:
- `role_implied`: infer at least 3–5 keywords from the `position_title`
  alone. You always have the position title even before reading the full ToR.
  Running on Sonnet, you have the reasoning capacity to produce role-implied
  keywords from the title alone — do not return an empty `role_implied` list
  unless `position_title` is itself empty.
- `explicit`: extract at minimum any geography and experience threshold
  requirements named in the ToR.

Returning all three lists empty for a non-empty ToR is treated as an A2
extraction failure by downstream validation.
```

#### 5b — New soft-flag check function in `pipeline/validators.py`

```python
def check_tor_summarizer_warnings(run_dir: Path) -> list[dict]:
    """
    Soft-flag check after Agent 2.

    Reads tor_data.json. For each pool in pools[]:
    - If all three scoring_keywords lists are empty AND the pool has non-empty
      content (position_title or key_tasks), emit kind 'scoring_keywords_empty'.
    - If position_title is empty AND the ToR has any content, emit kind
      'position_title_empty'.

    Returns [] when the file is missing, pools is empty (no-ToR run), or
    all checks pass.
    """
```

#### 5c — Wire in `run_phase1`

After `tor_summarizer.run(run_dir, tor_text)` (line 157 in orchestrator.py):
```python
# Fix Y: soft-flag check after A2 for empty scoring_keywords
for w in check_tor_summarizer_warnings(run_dir):
    log.info("Session %s soft-flag [%s]: %s", session_id, w["kind"], w["message"])
    append_warning(run_dir, **w)
```

Also add `check_tor_summarizer_warnings` to the import block.

#### Tests

**`tests/test_tor_summarizer_prompt.py`** — extend:
- `test_scoring_keywords_section_position` — asserts `scoring_keywords` section
  appears before `country_experience_required` section in the prompt (confirms reorder).
- `test_scoring_keywords_non_empty_guarantee_present` — asserts the non-empty
  guarantee language is present.

**`tests/test_validators.py`** — add `TestCheckTorSummarizerWarnings`:
- `test_missing_file_returns_empty`
- `test_healthy_tor_returns_empty` (all keyword lists populated, title present)
- `test_empty_scoring_keywords_flagged`
- `test_empty_position_title_flagged`
- `test_no_pools_returns_empty` (no-ToR case — empty pools list)
- `test_partial_keyword_list_not_flagged` (one list populated is sufficient)

---

### Step 6 — Full test suite + markdown updates

#### 6a — Run `pytest tests/` and verify ~422/422 passing

#### 6b — Markdown updates (6 files)

**`additions/PIPELINE_DIAGNOSTIC_CONTEXT.md`** (multi-purpose update):

1. Fix **doc inconsistencies** from Rounds 5 and the current status:
   - Update status header (lines 9–12) to reflect Round 5 completion.
   - Fix Issue U heading (line 308): change from `**PENDING (Fix U)**` to `**FIXED (Fix U)**`.
   - Fix table line 432 (Fix U): change from `⏳ Pending | Round 6` to `✓ Implemented | Round 5`.
   - Remove **duplicate rows** for Fix Z and Fix AA (lines 439–440 are exact copies of 437–438).
   - Fix **stale Fix X entry** (line 435): Issue X is closed as a false positive; remove Fix X from the fix table and Section 3 sequence (line 480).
   - Update **Round-by-round records list** (lines 18–22) to include `PIPELINE_DIAGNOSTIC_ROUND_5.md` and `PIPELINE_DIAGNOSTIC_ROUND_6.md`.
   - Update the **implementation status** header to reflect Round 6 completion.

2. Mark Issues V/W/Y/Z/AA as `✓ FIXED`.
3. Update Section 2 fix table: V/W/Y/Z/AA marked `✓ Implemented | Round 6`.
4. Update Section 3 sequence: Round 6 completed; Round 7 added (Fix S + threshold recalibration).
5. Update Section 4 round summary table.

**`additions/PIPELINE_DIAGNOSTIC_ROUND_6.md`**:
- Status → `Complete`
- Tests → `NNN/NNN passing`
- Rewrite "Planned fixes" → "Fixes delivered" with implementation details (mirrors Round 5 format).
- Add Files changed table.
- Add Test results line.
- Production validation placeholder.
- Issues surfaced placeholder.
- Markdowns updated list.
- Design decisions recorded (one per decision above).

**`markdowns/PROMPT_REVIEW_CONTEXT.md`**:
- 5 new rows in §5: Fix Z, Fix AA, Fix V, Fix W, Fix Y.
- §7 quickref: add A6 pre-processing truncation row; update A1 extraction row.

**`markdowns/PROMPT_REVIEW_IMPLEMENTATION.md`**:
- Append `## Round 7 — Diagnostic Fixes Round 6 (May 2026)` section with file table
  and test count.

**`markdowns/PIPELINE_CONTEXT.md`**:
- Compressor row: mention `_truncate_project_text_for_a6` and `append_warning` for truncation events.
- A1 extraction row: mention date ordering validation and merged-cell project extraction.

**`markdowns/RUNS_ARTIFACTS_CONTEXT.md`**:
- `cv_data.json` row: add Fix V (project_name warnings) and Fix W (date inversion warnings).
- `tor_data.json` row: note scoring_keywords non-empty guarantee.
- `manifest.json` row: note new `input_field_truncated` warning kind from Fix Z.

---

## Full files-changed summary

| File | Step | Nature |
|------|------|--------|
| `pipeline/agents/compressor.py` | 1 | `A6_INPUT_PROJECT_WORD_CAP`, `_A6_CAPPED_FIELDS`, `_truncate_project_text_for_a6`; call site in `run()`; `append_warning` calls for truncation events; new import |
| `pipeline/agents/fields_generator.py` | 2 | `SYSTEM_PROMPT_A4` minimum guarantee — WB `detailed_tasks` example added |
| `pipeline/agents/cv_extractor.py` | 3, 4 | `SYSTEM_PROMPT_A1` — `### Merged-cell and two-column project tables`; `### Date ordering validation` |
| `pipeline/agents/tor_summarizer.py` | 5 | `SYSTEM_PROMPT_A2` — `### scoring_keywords` moved earlier; non-empty guarantee added |
| `pipeline/validators.py` | 5 | `check_tor_summarizer_warnings` function added |
| `pipeline/orchestrator.py` | 5 | `check_tor_summarizer_warnings` imported and wired in `run_phase1` |
| `tests/test_compressor_text_cap.py` | 1 | **New file.** ~12 tests |
| `tests/test_fields_generator_prompt.py` | 2 | 2 new tests |
| `tests/test_cv_extractor_prompt.py` | 3, 4 | 6 new tests |
| `tests/test_tor_summarizer_prompt.py` | 5 | 2 new tests |
| `tests/test_validators.py` | 5 | ~6 new tests (`TestCheckTorSummarizerWarnings`) |
| `additions/PIPELINE_DIAGNOSTIC_CONTEXT.md` | 6 | Multi-purpose: inconsistency fixes + Round 6 status |
| `additions/PIPELINE_DIAGNOSTIC_ROUND_6.md` | 6 | Full implementation record |
| `markdowns/PROMPT_REVIEW_CONTEXT.md` | 6 | 5 new rows + §7 |
| `markdowns/PROMPT_REVIEW_IMPLEMENTATION.md` | 6 | Round 7 section appended |
| `markdowns/PIPELINE_CONTEXT.md` | 6 | Compressor + A1 rows updated |
| `markdowns/RUNS_ARTIFACTS_CONTEXT.md` | 6 | cv_data.json + tor_data.json + manifest.json rows updated |

---

## Risk and dependency notes

- **Fix Z information loss**: per the "truncate-and-warn" decision, content beyond
  word 150 per field is permanently excluded from compression scope. The manifest
  soft-flag is the only signal. Tests will verify the warning is always emitted when
  truncation occurs.

- **Fix Z import**: `compressor.py` does not currently import `append_warning`
  from `pipeline.manifest`. This import must be added.

- **Fix W coverage scope**: auto-correcting date inversions across all four field
  types could mask legitimate source-document quirks. The `extraction_warnings` entry
  per swap is the transparency mechanism — reviewers see every swap that was applied.

- **Fix Y reorder side-effects**: moving `### scoring_keywords` earlier changes the
  reading order for all ToR inputs (not just PDFs). The prompt-marker test for
  section position will catch any accidental reversion.

- **Doc inconsistency cleanup**: Rounds 5 and 6 both resulted in stale entries in
  the master diagnostic. This round's Step 6 resolves all identified inconsistencies.
  After Round 6, the master doc and the per-round files should be fully aligned.

---

## Deferred to Round 7

- **Fix S** — Compressor word target scaled to `page_limit`. Pending calibration
  data (minimum 5 clean rendered outputs per template per page count). See
  `COMPRESSION_CALIBRATION_CONTEXT.md`.

- **Fix 4 threshold recalibration** — Review `MIN_PROJECTS_TO_KEEP` (current code:
  5) and `MAX_PROJECTS_TO_KEEP` (current code: 15) and scoring thresholds
  (0.30/0.40/0.50) once Fix 4's Python scoring has produced a stable distribution
  across sufficient production runs.

---

## Re-implementation record (A1 prompt restructure + model upgrade)

### Changes made

**`pipeline/config.py`**
- `ANTHROPIC_MODEL`: `claude-sonnet-4-20250514` → `claude-sonnet-4-6`
- `ANTHROPIC_SYNTHESIS_MODEL`: `claude-sonnet-4-20250514` → `claude-sonnet-4-6`
- Comment updated to document the context window reason for the upgrade.

**`pipeline/agents/field_editor.py`**
- `MODEL`: `claude-sonnet-4-20250514` → `claude-sonnet-4-6`

**`pipeline/agents/cv_extractor.py` — `SYSTEM_PROMPT_A1` only**

- **Change A (schema position)**: `{{ CVData.model_json_schema() }}` placeholder
  moved from after `### Fields to leave empty` (end of prompt) to immediately
  after `## Output rules` (before `## Extraction rules`). The LLM now sees the
  output schema before reading extraction instructions, reducing late-instruction
  failure. No Python code change — `_build_prompt()` handles injection by string
  replacement regardless of placeholder position.

- **Change B (remove redundant GIZ fallback block)**: Removed the inline
  `NEVER leave relevant_projects empty` block with its `employer → company`
  field mapping from inside `#### GIZ`. That block contradicted the
  `### Employment-only fallback` section and used the wrong mapping. Replaced
  with a two-line pointer to the fallback section plus a `NEVER` guarantee.

- **Change C (fix field mapping in `### Employment-only fallback`)**: Changed
  `employer → company (also use as project_name)` to the correct mapping per
  `ISSUE_CC_CONTEXT.md`:
  - `employer → project_name`
  - `employer → client`
  - `Leave company, donor, main_project_features as "".`
  Added explicit statement: "This rule applies to ALL formats — for GIZ runs it
  means `relevant_projects` will NEVER be returned empty when the CV has any
  employment history."

- **Change D (tighten placeholder detection)**: Reduced `### Unfilled placeholder
  detection` from ~180 words to ~80 words. Removed underscore-gap and
  sentence-fragment patterns (low-signal). Kept: uppercase-in-numeric-context,
  bracket-delimited-token, warning format example, NOT-flag rule.

### Before / after prompt metrics

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Pre-schema prompt chars | 14,365 | 13,383 | −982 |
| Pre-schema prompt words | 2,040 | 1,904 | −136 |
| Full rendered prompt chars | 36,633 | 35,651 | −982 |
| Schema position (char offset) | 36,440 (end) | 191 (start) | before extraction |
| Model context window | 200k tokens | 1M tokens | 5× larger |

### Test results

**426/426 passing** — no test regressions.

### Why the field mapping mattered

The previous `employer → company` mapping placed the employer name in `company`,
leaving `project_name` empty. Empty `project_name` causes:
- A5 (content reviewer) to flag missing project names as high-severity.
- The renderer to produce blank project title cells in the output document.
- A4 to have weaker context for qualification bullet generation.

The correct mapping (`employer → project_name`) ensures the employer functions as
the project identifier, matching the intent of `ISSUE_CC_CONTEXT.md`.
