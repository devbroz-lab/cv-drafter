# Pipeline Diagnostic Context — Agent Quality & Data Flow Issues

**Date**: May 2026
**Scope**: Full pipeline review covering Agents 1–7, the GIZ renderer, and supporting
infrastructure. Based on live session artifacts (`cv_data.json`, `mapped_cv.json`,
`generated_fields.json`, `output.docx`) alongside all agent source files and the
renderer.

**Implementation status** (as of Round 8 — May 2026): Fixes 1, 3, 5a, 6, 7,
8 (Parts 1/2/3), 9, Fix J, Fix M (Parts 1 and 2), Round 4 fixes (R4-A through R4-E),
Round 5 fixes (R5-A through R5-E), Round 6 fixes (R6-A through R6-G), Round 7
fixes (R7-A through R7-M), and Round 7.5 fixes (R7.5-A through R7.5-I) are all
implemented. Round 8 fixes (R8-A, R8-B, R8-C, R8-D) are scoped and in progress.
Fix S, R5-B threshold recalibration, and ToR caching remain deferred to Round 9.

**Nomenclature note**: Fix labels follow the `R{round}-{letter}` scheme (see
`FIX_LABEL_RENAME_MAPPING.md`). Legacy pre-Round-4 labels (Fix 1, 3, 5a, 6, 7,
8, 9, J, M, S) are unchanged.

Cross-reference with: `PIPELINE_CONTEXT.md`, `RENDERER_CONTEXT.md`,
`PROMPT_REVIEW_CONTEXT.md`, `PROMPT_REVIEW_IMPLEMENTATION.md`,
`RUNS_ARTIFACTS_CONTEXT.md`, `RELEVANCE_SCORING_DESIGN.md`,
`RENDERER_ISSUES.md`.

Round-by-round implementation records:
- `PIPELINE_DIAGNOSTIC_ROUND_1.md`
- `PIPELINE_DIAGNOSTIC_ROUND_2.md`
- `PIPELINE_DIAGNOSTIC_ROUND_3.md`
- `PIPELINE_DIAGNOSTIC_ROUND_4.md`
- `PIPELINE_DIAGNOSTIC_ROUND_5.md`
- `PIPELINE_DIAGNOSTIC_ROUND_6.md`
- `PIPELINE_DIAGNOSTIC_ROUND_7.md`
- `PIPELINE_DIAGNOSTIC_ROUND_7.5.md`
- `PIPELINE_DIAGNOSTIC_ROUND_8.md`

---

## How this document is organised

Section 1 documents issues observed during live session runs, tracing each from
its origin through its downstream effects. Section 2 records the agreed fixes.
Section 3 gives the recommended implementation sequence. Section 4 gives a
high-level round summary; full implementation detail is in the per-round files.
Section 5 lists known gaps not yet addressed. Section 6 describes the ongoing
and iterative nature of the round structure.

---

## 1. Observed issues

### Issue A — Agent 4 silent content failure (critical) — **FIXED (Fix 1 + Fix 5a)**

**What was observed**: In `generated_fields.json`, the `generated_fields` list
contained the correct number of entries with the correct `field_key` and `source`
values, but every `content` field was an empty string. The scaffolding existed;
the substance did not.

**Why it is silent**: The output parser in `fields_generator.py` validates the
LLM response against the `CVData` Pydantic schema. That schema places no minimum
length constraint on `GeneratedField.content`. Empty strings are structurally
valid. Validation passes, the file is written, and the pipeline advances with no
exception raised and no manifest step marked failed.

**Cascade through the pipeline**:
- Agent 5 receives empty generated content and does not flag it — its prompt
  contains no instruction to check whether `generated_fields[].content` is
  populated.
- Agent 6 counts zero words across `generated_fields`, finds the total word
  count already within the compression target, skips its LLM call entirely,
  and writes `applied: false`. The empty content passes through unchanged.
- The renderer's `_build_context` in `giz.py` detects that all `generated_fields`
  entries for `key_qualifications` have empty content and falls back to the raw
  `key_qualifications` list extracted by Agent 1. The document is rendered with
  A1's untailored extraction rather than A4's ToR-grounded bullets. No error is
  surfaced.
- Agent 7, called post-completion, inspects the active key qualifications source
  via its internal routing logic. Finding `generated_fields` empty, it routes all
  edits to the raw `key_qualifications` list instead. This routing is correct but
  silent — the user has no signal that their edits are targeting A1's extraction
  rather than A4's generated content.

**Root cause**: Agent 4 is the only agent in the pipeline that synthesises new
content rather than transforming existing content. It receives multiple dense input
blocks (`cv_data`, `tor_data`, `format_profile`, `params`) and must produce
ToR-grounded qualification bullets. This is a generative synthesis task. Haiku is
well-suited to structured extraction and transformation tasks but is unreliable on
multi-source synthesis under token pressure.

**Resolution**: Fix 1 upgraded A4 to `claude-sonnet-4-20250514` via
`ANTHROPIC_SYNTHESIS_MODEL` in `pipeline/config.py`. Fix 5a added a hard-block
validator (`pipeline/validators.py → validate_fields_generator_output`) that
fires before A5 if every `generated_fields[].content` is empty, overriding the
`fields_generator` manifest step to `failed` and calling `set_failed()`.

---

### Issue B — Dual-representation language schema (structural liability) — **FIXED (Fix 3)**

**What was observed**: Language entries contained six structured fields that were
empty strings in every entry across every agent. Only the `*_raw` fields were
populated. The schema carried six permanently empty fields through every artifact.

**Resolution**: `_populate_cefr_fields(parsed: CVData)` added to
`pipeline/agents/cv_extractor.py`. Maps `*_raw → *_cefr` for every language entry
whose structured field is empty. The renderer's `_resolve_cefr` fallback and
Agent 7's CEFR enrichment block remain as defensive layers but are no-ops for
new sessions. See `PIPELINE_DIAGNOSTIC_ROUND_1.md`.

**Residual issue**: Fix 3 exposed normalisation gaps in `map_cefr` — see Issue G.

---

### Issue C — Relevance scoring delegated to LLM arithmetic (consistency risk) — **FIXED (R5-B)**

**What was observed**: Agent 3's scoring is entirely LLM-side. The system prompt
specifies a four-dimensional weighted scoring model (sector keywords 35%, key
tasks 30%, competencies 20%, geography 15%) and asks the LLM to assign scores
and make keep/drop decisions. LLMs are inconsistent at weighted arithmetic across
sessions. The `_precompute_relevance_scores` stub currently returns `None`.

**Additional observation**: The `duration` pre-compute runs inside
`fields_generator.py` — after A3 has already scored and filtered projects.
A3's LLM therefore scores projects with no `duration` field populated.

---

### Issue D — No semantic validation between pipeline stages — **PARTIALLY FIXED (Fix 5a implemented; R5-D implemented)**

**What was observed**: `manifest.py` `done` status means only that the agent
completed without raising a Python exception. No check exists that output is
semantically useful.

**Partial resolution (Fix 5a)**: The A4→A5 hard-block gap is now closed by
`validate_fields_generator_output` in `pipeline/validators.py`. Remaining gaps
(A5→A6 review block check, A6→renderer compression check) and soft-flag warnings
are deferred as R5-D. See `PIPELINE_DIAGNOSTIC_ROUND_1.md`.

---

### Issue E — Agent 7 routing decision not surfaced via API — **FIXED (Fix 6)**

**Resolution**: `kq_source_label(generated)` added to `field_editor.py`. `run()`
returns `(applied, skipped, kq_source)` where `kq_source` is one of
`"ai_generated"` / `"extracted"` / `"absent"`. Included as a required field in
`FieldEditResponse`. See `PIPELINE_DIAGNOSTIC_ROUND_1.md`.

---

### Issue F — `years_with_firm` unconditional param injection — **CLOSED**

Acknowledged as intentional behaviour. Not a bug in the general case.

---

### Issue G — `map_cefr` normalisation gaps for non-standard input formats — **FULLY FIXED (Fix 7 + Fix M Part 1)**

**What was observed**: Parenthetical format ("Proficient (C2)") and numeric scale
format produced incorrect or sentinel CEFR values in the rendered document.

**Resolution**: Parenthetical extraction added in Fix 7. Full numeric scale mapping
(`1→C1`, `2→B2`, `3→B1`, `4→A2`, `5→A1`) added in Fix M Part 1. `"?"` sentinel
now reserved for genuinely unresolvable inputs only.

**Residual**: Scale direction assumed fixed (`1=C1`). See Issue O.

See `PIPELINE_DIAGNOSTIC_ROUND_2.md` and `PIPELINE_DIAGNOSTIC_ROUND_3.md`.

---

### Issue H — Agent 3 keeps too many projects for large CVs, causing Agent 4 token exhaustion — **FIXED (Fix 8 Part 1 + Fix J)**

**Root cause**: A3 had a floor but no ceiling. For large CVs, the threshold alone
was insufficient to bound A4's input to a workable size.

**Resolution**: `MAX_PROJECTS_TO_KEEP = 6` cap added. `_enforce_threshold_and_cap`
in `cv_tor_mapper.py` applies cap after threshold enforcement and minimum guarantee.
See `PIPELINE_DIAGNOSTIC_ROUND_2.md`.

---

### Issue I — `FieldShortened.subfield` schema rejects null values from Agent 6 — **FIXED (Fix 9)**

**Resolution**: `FieldShortened.subfield: str | None = Field(default=None, ...)` in
`models.py`. See `PIPELINE_DIAGNOSTIC_ROUND_2.md`.

---

### Issue J — Agent 3 threshold enforcement unreliable — **FIXED (Fix J)**

**Resolution**: `_enforce_threshold_and_cap` in `cv_tor_mapper.py` deterministically
enforces thresholds post-LLM. See `PIPELINE_DIAGNOSTIC_ROUND_2.md`.

---

### Issue K — Agent 4 fails to generate when CV-ToR alignment is weak — **FIXED (Fix 8 Part 2)**

**Resolution**: `## OUTPUT PRIORITY ORDER` and `### Minimum output guarantee` added
to `SYSTEM_PROMPT_A4`. See `PIPELINE_DIAGNOSTIC_ROUND_2.md`.

---

### Issue L — Token exhaustion from few but extremely large projects (World Bank) — **FIXED (Fix 8 Part 3)**

**Resolution**: `A4_INPUT_PROJECT_WORD_CAP = 150` and `_truncate_project_text_for_a4`
added to `fields_generator.py`. See `PIPELINE_DIAGNOSTIC_ROUND_2.md`.

---

### Issue M — Fix 8 Part 3 truncation marker leaks into `generated_fields.json` — **FIXED (Fix M Part 2)**

**Resolution**: `_restore_truncated_project_text` helper added to
`fields_generator.py`. See `PIPELINE_DIAGNOSTIC_ROUND_3.md`.

---

### Issue N — Agent 3 project floor too low; cap too aggressive (over-dropping) — **FIXED (R4-A)**

**What was observed**: Across Runs 4, 5, and 6 of Round 3, A3 consistently
produced CVs with only 2–6 projects from candidates with 12–24 project histories.
Projects scoring 0.45–0.72 representing genuine relevant experience were discarded.
A CV of 2 projects is not viable in any real-world submission context.

**Downstream effect on A5**: A5 cannot distinguish between a gap caused by project
dropping and a genuine candidate-ToR mismatch. In Run 6, A5 flagged an experience
gap that was entirely artificial — caused by A3 discarding 10 legitimate projects.

**Recommended fix**:
- Raise `MIN_PROJECTS_TO_KEEP` from `2` to `3`, with dynamic floor
  `min(3, total_projects)`.
- Lower thresholds by 0.10: `0.30 / 0.40 / 0.50` (by project count bracket).
- Raise `MAX_PROJECTS_TO_KEEP` from `6` to `10`.

Constants should be treated as interim values pending R5-B. See
`PIPELINE_DIAGNOSTIC_ROUND_3.md` for full artifact evidence.

---

### Issue O — `map_cefr` numeric scale direction assumed fixed (1=C1) — **PENDING (R4-B)**

**What was observed**: Round 3 Run 4 source CV states `"1 – excellent; 5 – basic"`,
meaning `1 = C2`. Fix M Part 1 mapped `1 → C1`, producing the wrong level. A1
correctly flagged the ambiguity in `extraction_warnings` but the hard-coded
mapping overrode it.

**Recommended fix**: A1 emits `language_scale_direction` (`"1_best"` / `"1_worst"`
/ `null`). `_populate_cefr_fields` inverts the mapping when `"1_best"` is detected:
`1→C2, 2→C1, 3→B2, 4→B1, 5→A2`.

---

### Issue P — Agent 4 synthesises new KQ bullets instead of condensing candidate's own text — **FIXED (R4-C)**

**What was observed**: Round 3 Run 4 — A1 correctly extracted 9 bullet-style
`key_qualifications` matching the expected output style. A4 discarded them and
generated new thematic bullets instead.

**Recommended fix**: Add preference instruction to `SYSTEM_PROMPT_A4` — when
`key_qualifications` contains bullet-format entries reasonably aligned with the
ToR, prefer selecting and lightly editing those over generating from scratch.

---

### Issue Q — `other_skills` field not populated; certifications data not routed correctly — **FIXED (R4-Q)**

**What was observed**: Round 3 Run 4 — source CV has a "Other skills" section.
A1 routed its content to `certifications[]` but left `other_skills: []` empty.
The renderer reads `other_skills`, so the section renders blank.

**Recommended fix**: Update A1's prompt to populate `other_skills` from content
explicitly labelled "Other skills" in the source document.

---

### Issue R — `references` and `certification_declaration` fields absent from A1 schema — **FIXED (R4-E)**

**What was observed**: Round 3 Run 6 — source CV contains a References section
(3 named contacts) and a certification declaration block. Neither key exists in
A1's output schema. Treated as optional fields.

**Recommended fix**:
- Add `references: list[Reference] | None = None` to `CVData`.
- Add `certification_declaration: str | None = None` to `CVData`.
- Update A1's prompt and both renderers accordingly. Both fields default to `None`;
  no existing sessions affected.

---

### Issue S — Compressor word target not scaled to page limit — **PENDING (Fix S)**

**What was observed**: Round 4 Run 3 (GIZ, `page_limit=2`) — compressor applied
`target_words=900`, the same target used for a 1-page CV, resulting in a 49% word
reduction (1,058 → 534 words). The compressor operated correctly against its target;
the target itself is wrong for a 2-page submission. Despite the aggressive compression,
the rendered document still exceeded 2 pages — see Issue T.

**Root cause**: `target_words` is computed without reference to `page_limit`. The
compressor has no awareness that a multi-page CV requires a proportionally higher
word budget.

**Recommended fix**: Introduce `TARGET_WORDS_PER_PAGE` as a per-donor constant in
`pipeline/config.py` (e.g. `GIZ_WORDS_PER_PAGE = 500`, `WB_WORDS_PER_PAGE = 550`).
Compute `target_words = page_limit * TARGET_WORDS_PER_PAGE` in the orchestrator or
compressor before the compression step. Constants to be calibrated against real
rendered output per template.

---

### Issue T — Layout-driven page overflow not reducible by compression — **CLOSED (out of pipeline scope)**

**What was observed**: Round 4 Run 3 — after compressing to 534 words, the rendered
document still exceeded 2 pages. Page count is driven by fixed structural elements
in the GIZ Word template (tables, section headers, margins, fonts) rather than prose
word count alone. Further compression would not resolve the overflow.

**Resolution**: Word template layout issue, not a pipeline defect. The pipeline can
only control word count, not rendered page geometry. Closed.

---

### Issue U — A1 extracts unfilled placeholder text verbatim — **FIXED (R5-E)**

**What was observed**: Round 4 Run 3 — source CV contains `"More than X years
experience as Team Leader"` where `X` is a literal unfilled placeholder. A1 extracted
this verbatim into `key_qualifications`. A5 correctly flagged it as incomplete and
unclear. The pipeline did not detect or warn about the malformed input at extraction
time.

**Root cause**: A1's prompt has no instruction to detect unfilled placeholders
(standalone uppercase letters in numeric contexts: `X`, `N`, `Y`).

**Recommended fix**: Extend A1's prompt to detect and append an `extraction_warnings`
entry when a likely unfilled placeholder is found (e.g. `"key_qualifications[3]
contains likely unfilled placeholder: 'More than X years experience as Team Leader'."`).
A1 still extracts the text faithfully; the warning surfaces it for human review.
No schema changes required.

---

### Issue V — A1 fails to extract `project_name` and details from merged-cell table layout — **FIXED (R6-A)**

**What was observed**: Round 5 Run 4 — 11 of 24 projects had blank `project_name`
and empty detail fields. Source CV uses a two-column table with merged cells where
the left column contains project title and dates. A1 created correct entry count
but failed to map the title to `project_name`.

**Recommended fix**: Extend A1's prompt to explicitly extract `project_name` from
the left/title column of two-column project tables regardless of cell merge formatting.

---

### Issue W — A1 inverts `date_from` / `date_to` for `countries_of_experience` — **FIXED (R6-B)**

**What was observed**: Round 5 Run 4 — all `countries_of_experience` entries had
`date_from` and `date_to` swapped, rendering end date before start date in output.

**Recommended fix**: Extend A1's prompt to validate date ordering for
`countries_of_experience` — `date_from` must be chronologically earlier than
`date_to`. Auto-correct the swap and add an `extraction_warnings` entry when detected.

---

### Issue X — Renderer empty bullet placeholders — **CLOSED (false positive)**

**What was observed**: Text extraction showed empty bullet markup in "Other relevant
information". On inspection of actual rendered Word documents for Runs 4 and 5,
no empty bullets were visible. The placeholder markup exists in template XML but
does not render visibly in Word. Closed as a false positive from the text extraction tool.

---

### Issue Y — A2 produces empty `scoring_keywords` despite rich ToR content — **FIXED (R6-D)**

**What was observed**: Round 5 Run 4 — all three `scoring_keywords` lists empty
despite a 36-page PDF ToR with explicit requirements. R5-B's Python scorer had
no keywords, producing near-uniform scores (0.20–0.28). Round 5 Run 5 confirmed
R5-A working correctly on a non-PDF ToR — all keyword lists fully populated.

**Root cause**: A2's keyword extraction section not firing on PDF-sourced content,
or being deprioritised on long inputs. PDF-specific issue.

**Recommended fix**: Move scoring keywords instruction earlier in `SYSTEM_PROMPT_A2`;
add `generation_warnings` entry when all lists are empty.

---

### Issue Z — Compressor JSON truncation on large input — **FIXED (R6-E)**

**What was observed**: Round 5 Run 6 (WB format, `page_limit=4`) — compressor
failed with `"Expecting ',' delimiter: line 403 column 171 (char 14574)"`.
A6's LLM response was truncated mid-JSON. 1,696 words of `activities_performed`
across 5 projects (first project alone: 694 words) exceeded A6's effective output
budget. Fix 8 Part 3 caps A4's input but A4 can expand content in its output;
Fix M Part 2 correctly restores originals — so A6 sees the full untruncated volume
with no equivalent cap.

**Recommended fix**: Apply a word cap to A6's input assembly, mirroring Fix 8
Part 3's pattern for A4. Truncate `activities_performed` in A6's input only;
preserve originals for artifact write.

---

### Issue AB — `relevant_projects` empty for employment-only format CVs — **FIXED (R6-G)**

**What was observed**: Round 6 Run 4 (Jennifer Garvey, GIZ, South Africa ToR) —
`cv_data.json` had `relevant_projects: []` and `employment_record` with 12 fully
populated entries. A3 had nothing to score; A4 generated only 4 thin KQ bullets;
the rendered document had a blank "Work undertaken" section.

**Root cause**: A1 routes experience to `employment_record` when the source CV has
no dedicated project table. A3 scores only `relevant_projects`, so the pipeline
proceeds with zero project content.

**Resolution**: `### Employment-only fallback (all formats)` section added to
`SYSTEM_PROMPT_A1`. When `relevant_projects` would otherwise be empty and
`employment_record` has entries, each employment entry is mapped to a
`RelevantProject` using this routing:

| `employment_record` field | → `relevant_projects` field |
|---|---|
| `employer` | `project_name` |
| `employer` | `company` |
| `positions_held` | `positions_held` |
| `description` | `main_project_features` |
| `from_date` / `to_date` | `date_from` / `date_to` |
| `location` / `country` | `location` |

`client`, `donor`, and `activities_performed` are left as `""`. A Python safety
net (`_apply_employment_fallback`) mirrors the same mapping. Short-description
entries (< 5 words) emit a per-entry `extraction_warnings` entry referencing
`main_project_features`.

---

### Issue R7-1 — All-projects-below-threshold: quality signal breaks down — **OBSERVATION (no fix)**

**What was observed**: Runs 1, 5, 7 (Round 7) — all kept projects scored below the
relevance threshold; floor guarantee activated for all five. A4 generated polished
hedged bullets for a fundamentally misaligned candidate. Pipeline behaviour is
correct (generate best available, flag heavily, block at reviewer) but the output
quality signal is degraded when the floor overrides all threshold decisions.

**Resolution**: No pipeline fix needed. Correct behaviour. Recorded for awareness.

---

### Issue R7-2 — Lexical keyword scorer misses regional-to-national vocabulary overlap — **OBSERVATION (no fix)**

**What was observed**: Run 1 Round 7 — SAEP Outcome 3 project (regional SAPP
transmission work) scored 0.20 against a South Africa-specific ToR. The work is
SA-relevant but the CV uses "Southern Africa / SAPP" language. Lexical matching
cannot detect the semantic overlap.

**Resolution**: Known limitation of lexical matching. Tied to future
embedding-based semantic scoring. No fix in current scope.

---

### Issue R7-3 — CLOSED

Suspected: empty `activities_performed` on WB-format CVs impairs A3 keyword
scoring. Confirmed not a bug — `keyword_overlap_score` in `precompute_utils.py`
already checks all four project fields including `main_project_features`. Low
scores in Run 2 were genuine. Closed.

---

### Issue R7-4 — Placeholder KQ entries reaching A4 — **OBSERVATION (keep-and-warn)**

**What was observed**: Run 3 Round 7 (Stojadinovic, 43-project CV) — source CV
contained unfilled template placeholders in `key_qualifications` (e.g. "X years
experience in [mention area]"). A1 correctly warned via `extraction_warnings`;
A4 correctly worked around them and emitted generation warnings.

**Resolution**: Keep-and-warn behaviour confirmed correct. Information is preserved;
the LLM is tolerant of partial placeholder content. No fix needed.

---

### Issue R7-5 — Education rows not sorted newest-first in GIZ renderer — **FIXED (R7-G)**

**What was observed**: Runs 2 and 3 Round 7 — education entries in GIZ output
Table 1 rendered in source CV order (oldest-first) rather than GIZ convention
(newest-first).

**Recommended fix**: Sort education list descending by `date_to` in
`_build_context` in `templates/giz.py`.

---

### Issue GG — Education date duplication in GIZ renderer — **FIXED (R7-E)**

**What was observed**: Runs 1, 2, 3, 5 Round 7 — education rows in GIZ Table 1
show date range twice. Three variants: standard duplication, missing `date_from`,
and single-year entry.

**Root cause**: `_build_context` in `giz.py` constructs `institution` as
`f"{institution} [{date_range}]"` and also passes `date_from`/`date_to` as
separate template variables, causing both to render in the same cell.

**Recommended fix**: Remove `[{date_range}]` suffix from the institution string.

---

### Issue HH — Ampersand `&` stripping in GIZ renderer — **FIXED (R7-F)**

**What was observed**: Runs 3 and 5 Round 7 — ampersand characters stripped in
rendered output: "Legal & Policy" → "Legal  Policy". Affects all text fields.

**Root cause**: Raw `&` in manually-constructed strings bypasses `docxtpl`'s XML
escaping.

**Recommended fix**: Ensure all manually-constructed strings pass through Jinja2
rendering or apply `html.escape()` before context insertion.

---

### Issue II — Field Editor (A7) and renderer not in sync on rendered field scope — **FIXED (R7-H, R7-I)**

**What was observed**: (a) WB renderer pairs `detailed_tasks[i]` to
`relevant_projects[i]` by pure list position. R7-B re-sorting projects would
break this pairing. (b) A7 can edit `relevant_projects[i].activities_performed`
on GIZ runs — the edit writes correctly to `generated_fields.json` but is never
rendered in GIZ output (field not placed in any cell by `giz_dynamic_template.py`).

**Recommended fix**: (a) Apply R7-B sort at mapper write-time so A4 generates
tasks in already-sorted order — no renderer change needed. (b) Add
`RENDERER_FIELD_MAP` to A7 per donor; redirect or warn on non-rendered field edits.

---

### Issue JJ — A4 truncation-and-restore unnecessary with current model — **FIXED (R7-J)**

**What was observed**: `_truncate_project_text_for_a4` caps A4's input to 150
words per project field. `_restore_truncated_project_text` correctly restores
originals before artifact write. Both steps are redundant with
`claude-sonnet-4-6`'s 200k context window. Limits A4's grounding quality.

**Recommended fix**: Remove both helpers and the associated `cv_data_full`
preservation step from `fields_generator.run()`.

---

### Issue KK — A6 truncation causes silent permanent data loss — **FIXED (R7-K)**

**What was observed**: `_truncate_project_text_for_a6` caps A6's input to 150
words per project field with no restoration step. Run 6 Round 7: BADGE project
`activities_performed` truncated from 694 to 150 words — 544 words permanently
lost, not compressed.

**Root cause**: R6-E was introduced for an earlier, smaller model. With
`claude-sonnet-4-6` and `max_tokens=16000` on the output side only, there is no
truncation risk from full-length input.

**Recommended fix**: Remove `_truncate_project_text_for_a6` and all associated
constants, call sites, and manifest warning emissions entirely.

---

### Issue LL — A6 compresses `activities_performed` for GIZ runs despite field not being rendered — **FIXED (R7-L)**

**What was observed**: GIZ renderer (`giz_dynamic_template.py`) never places
`activities_performed` in any table cell, despite `giz.py` passing it to the
template context. A6 compresses this field for GIZ runs, wasting compression
budget on a field that does not appear in the output document.

**Recommended fix**: Pass donor format to A6; exclude `activities_performed` from
the GIZ compressible field set in both the word-count arithmetic and the prompt.
WB runs are unaffected — `activities_performed` is rendered in WB output.

---

### Issue MM — Pipeline warnings not transmitted to frontend via API — **FIXED (R7-M)**

**What was observed**: `extraction_warnings`, `alignment.warnings`, and
`manifest.warnings` are written to disk correctly but no API endpoint reads or
transmits them to the frontend. Only `generation_warnings`, `review.high_severity`,
and `review.low_severity` from `generated_fields.json` reach the UI.

**Recommended fix**: Extend `api/routers/sessions.py` to aggregate and transmit
all warning types. Display/abstraction decisions are the UI developer's
responsibility.

---

### Issue R7.5-A — A5 flags passive constructions in source-extracted fields — **FIXED (R7.5-A)**

**What was observed**: Runs 1–4 Round 7.5. A5 flags `activities_performed` and
`main_project_features` for passive/infinitive verb constructions. These are direct
extractions of the candidate's own words. Style flags inflate issue count, push
runs over the `high_severity_count_unusual` threshold, and produce recruiter-facing
review items that cannot be acted on.

**Recommended fix**: Add scope restriction to `SYSTEM_PROMPT_A5` — style checks
permitted only on `generated_fields[*].content`. Source-extracted fields are out
of scope for style review but remain in scope for factual accuracy checks.

---

### Issue R7.5-C — A4 generates verb-led KQ bullets; convention is noun/stat-led — **FIXED (R7.5-B)**

**What was observed**: Runs 2, 3, 4 Round 7.5. A4 generates verb-led bullets
("Delivered...", "Drafted...", "Conducted..."). Human editors use noun-phrase or
year-count-led bullets ("25 years of professional experience...", "8 years of
experience in Grid codes..."). Runs 3 and 4 produced near-identical bullets for
different candidates against the same ToR — A4 over-indexes on ToR requirements
and under-differentiates on candidate-specific evidence.

**Recommended fix**: Add to `SYSTEM_PROMPT_A4`: (a) strong preference for
noun/stat-led KQ bullet openings; (b) candidate-anchoring rule requiring at least
one candidate-specific detail per bullet. Applies to both GIZ and WB formats.

---

### Issue R7.5-E — Project cap too aggressive; current role dropped on geography mismatch — **FIXED (R7.5-C, R7.5-D)**

**What was observed**: Runs 2, 3, 4 Round 7.5. Human versions include 19–21
projects; pipeline keeps 5–9. Kostari's current role (Power Central Asia,
01/2021–present) dropped because geography does not match Western Balkans ToR.
Human editors always include the current role regardless of geographic fit.

**Recommended fix**: (a) Broaden A3 keyword scoring tolerance; raise MIN=10,
MAX=30. (b) Add `_protect_current_role` Python step in `cv_tor_mapper.py` to
unconditionally restore any `date_to = "Present"` project dropped by cap
enforcement.

---

### Issue R7.5-F — Education table includes marginal training/seminar entries — **FIXED (R7.5-E, R7.5-F)**

**What was observed**: Runs 2, 3 Round 7.5. Pipeline includes short courses,
seminars, and training programs in GIZ Table 1 alongside degree qualifications.
Human editors retain only degree-level qualifications.

**Recommended fix**: (a) A1 prompt: `education[]` for degree-level qualifications
only; non-degree entries → `training[]`. (b) A4 prompt: draw from `training[]` as
additional KQ evidence source (mirrors R7-D pattern for `certifications[]`).
Alternative 3 selected over A1-side appending to `key_qualifications[]`.

---

### Issue R7.5-H — R7-B bug: `countries_of_experience` sorted by wrong key — **FIXED (R7.5-G)**

**What was observed**: Run 4 Round 7.5 (Kostari). Kosovo (01/1999–present) sorts
third because R7-B sorts `countries_of_experience` by `date_from` descending,
placing 1999 last. Ongoing assignments should float to top.

**Recommended fix**: Change sort key for `countries_of_experience` to `date_to`
descending. `_parse_date` already returns `_current_date()` for "Present", so
ongoing assignments sort highest naturally.

---

### Issue R7.5-I — `countries_of_experience` identical date-range rows not collapsed — **FIXED (R7.5-H)**

**What was observed**: Human CVs collapse countries sharing identical date ranges
into one row. Pipeline renders one row per country entry.

**Recommended fix**: Add `collapse_by_date_range` to `precompute_utils.py` (exact
match on `(date_from, date_to)` only; deterministic; general-purpose). Apply at
mapper write-time so both renderer and A7 see the same collapsed data. Processing
order in `cv_tor_mapper.py`: enforce cap → protect current role → sort projects →
collapse countries → sort countries → write.

---

### Issue R7.5-J — GIZ dual nationality uses "/" separator instead of "and" — **FIXED (R7.5-I)**

**What was observed**: Run 4 Round 7.5 (Kostari). Human version: "Republic of
Montenegro and Republic of Kosovo". Pipeline: "Republic of Montenegro / Republic of
Kosovo".

**Recommended fix**: Change `nationality_display` construction in `giz.py`
`_build_context` from `f"{nat1} / {nat2}"` to `f"{nat1} and {nat2}"`.
Unconditional for all GIZ dual-nationality entries. WB renderer unaffected.

---

### Issue R8-1 — A5 style miscalibration on generated KQ bullets — **FIXED (R8-A)**

**What was observed**: Runs 1 and 3, Round 8 validation. A5 flags noun/stat-led
openings on generated KQ bullets as missing action verbs — directly conflicting
with R7.5-B. Examples: *"missing an action verb at the start"* (Run 1),
*"passive construction leading with an adjective"* (Run 3). R7.5-A
correctly stopped A5 from flagging source-extracted fields, but A5's style
expectations for generated KQ content were not updated to match R7.5-B's convention.

**Recommended fix**: Add explicit style alignment to `SYSTEM_PROMPT_A5` — noun/
stat-led KQ bullet openings are the preferred convention per R7.5-B and must not
be flagged as missing action verbs or passive constructions.

---

### Issue R8-2 — R7.5-E edge case: partial credit certificate in `education[]` — **FIXED (R8-B)**

**What was observed**: Run 5, Round 8 validation (Jennifer Garvey). "Credit
Certificate towards Juris Doctor degree granted by University of Wisconsin" routed
to `education[]`. R7.5-E routes seminars and short courses to `training[]`
but the routing rule does not explicitly address partial credits and non-completing
enrolments.

**Recommended fix**: Sharpen `SYSTEM_PROMPT_A1` education routing — add explicit
exclusion for partial credit certificates, credit-towards-degree programmes, and
non-completing enrolments. A qualification must have a completed, named degree
title to enter `education[]`.

---

### Issue R8-3 — Runtime scaling with CV complexity — **FIXED (R8-C, R8-D)**

**What was observed**: All Round 8 validation runs. A1 runtime scales from ~41s
(5-project GIZ) to ~218s (43-project GIZ) to ~426s (13-project WB). WB format is
disproportionately slow due to additional extraction of `employment_record`,
`detailed_tasks`, and `world_bank_affiliation`. A3 also scales with project count
(88s → 250s). Root cause: R7-J/R7-K removed the 150-word input cap; agents now
process full project text.

**Recommended fix**: (a) Reinstate smart 300-word cap for A3 and A4 inputs with
restoration step for A4. (b) Add complexity pre-screen before A1 to warn recruiter
when CV exceeds size threshold.

---

### Issue R8-4 — Compressor `target_not_reached` on WB runs — **OBSERVATION (deferred to Fix S)**

**What was observed**: Run 6, Round 8 validation (Rafael Jabba Jr., WB, 4 pages).
Compressor reduced 3,770 → 2,108 words against a 1,800-word target. WB format
is structurally denser than GIZ — includes employment records and detailed tasks
alongside project descriptions. The 450 words/page constant is too low for WB.

**Resolution**: Fix S calibration issue. Separate `words_per_page` constants for
GIZ and WB are needed. Deferred to Round 9. WB constant suggested at ~600–650
words/page based on Run 6 data point.

---

### Issue R8-5 — Renderer issues A and B (countries_of_experience) — **SEE RENDERER_ISSUES.md**

**What was observed**: Round 7.5 post-implementation testing. Two rendering
defects in `countries_of_experience` table:
- Empty `date_to` entries sort to bottom of table instead of floating to top
  (Issue A in RENDERER_ISSUES.md — found Round 7.5 Run 4).
- Empty `date_to` renders as trailing dash "2023 -" instead of just "2023"
  (Issue B in RENDERER_ISSUES.md — found Round 7.5 Run 1).

**Full detail**: See `RENDERER_ISSUES.md`. These are renderer/mapper issues
handled separately from the pipeline diagnostic scope.

---

### Issue DD — A1 routes "References" section citations to wrong field — **FIXED (R7-A)**

**What was observed**: Source CVs with a "References" section containing academic
citations may be routed to `references[]` (contact reference schema) rather than
`publications[]`.

**Recommended fix**: Add explicit routing rule to `SYSTEM_PROMPT_A1` — citations
(author, title, journal/year) → `publications[]`; contact references (name, org,
email/phone) → `references[]`.

---

### Issue FF — Certifications not routed to `certifications[]` or used by A4 — **FIXED (R7-C, R7-D)**

**What was observed**: Run 2 Round 7 (Hadjicostas) — "Eur Ing" and "C Eng"
credentials present in source CV but `certifications: []` in cv_data. Content
routed exclusively to `membership_professional_bodies`. A4 has no instruction to
draw from `certifications[]` when generating KQ bullets.

**Recommended fix**: (a) A1 prompt: route formal credentials to both
`certifications[]` and `membership_professional_bodies`. (b) A4 prompt: treat
`certifications[]` as eligible KQ source material.

---

### Issue AA — A4 `detailed_tasks` empty on geographic mismatch (WB format) — **FIXED (R6-F)**

**What was observed**: Round 5 Run 6 — WB format, `detailed_tasks` in
`generative_field_keys`. A4 produced 0 entries. Generation warning flagged
geographic misalignment (The Gambia). Fix 8 Part 2's minimum output guarantee
did not fire for `detailed_tasks`.

**Root cause**: Minimum output guarantee in `SYSTEM_PROMPT_A4` may be scoped to
`key_qualifications` only, not all `generative_field_keys` entries.

**Recommended fix**: Update `SYSTEM_PROMPT_A4` minimum output guarantee to
explicitly reference all `generative_field_keys` entries — for WB format,
`detailed_tasks` must always have at least one entry regardless of alignment.

---

## 2. Agreed fixes

| Fix | Description | Status | Detail |
|-----|-------------|--------|--------|
| Fix 1 | Upgrade Agent 4 to Sonnet | ✓ Implemented | Round 1 |
| R5-C | Upgrade all remaining agents to Sonnet | ✓ Implemented | Round 5 |
| Fix 3 | Centralise CEFR mapping at Agent 1 write time | ✓ Implemented | Round 1 |
| R5-B | Python relevance scoring for Agent 3 + duration upstream | ✓ Implemented | Round 5 |
| Fix 5a | Hard-block validator after Agent 4 | ✓ Implemented | Round 1 |
| R5-D | Soft-flag quality warnings in manifest | ✓ Implemented | Round 5 |
| Fix 6 | Surface Agent 7 routing decision via API | ✓ Implemented | Round 1 |
| Fix 7 | `map_cefr` normalisation (parenthetical + numeric sentinel) | ✓ Implemented | Round 2 |
| Fix 8 Part 1 | Hard project cap (`MAX_PROJECTS_TO_KEEP = 6`) | ✓ Implemented | Round 2 |
| Fix 8 Part 2 | A4 prompt priority order + minimum output guarantee | ✓ Implemented | Round 2 |
| Fix 8 Part 3 | Per-project text cap in A4 pre-processing | ✓ Implemented | Round 2 |
| Fix 9 | `FieldShortened.subfield` optional | ✓ Implemented | Round 2 |
| Fix J | Python threshold enforcement for Agent 3 | ✓ Implemented | Round 2 |
| Fix M Part 1 | Numeric 1–5 CEFR scale mapping | ✓ Implemented | Round 3 |
| Fix M Part 2 | Fix 8 Part 3 truncation-text restoration | ✓ Implemented | Round 3 |
| R4-A | Raise floor, lower thresholds, raise cap | ✓ Implemented | Round 4 |
| R4-B | Numeric CEFR scale direction detection | ✓ Implemented | Round 4 |
| R4-C | A4 prompt: prefer candidate's own KQ bullets | ✓ Implemented | Round 4 |
| R4-D | A1 prompt: route `other_skills` correctly | ✓ Implemented | Round 4 |
| R4-E | Optional `references` and `certification_declaration` | ✓ Implemented | Round 4 |
| R5-A | A2 keyword extraction for Python relevance scoring | ✓ Implemented | Round 5 |
| Fix S | Compressor word target scaled to `page_limit` | ⏳ Deferred | Round 7 |
| R5-E | A1 unfilled placeholder detection in `extraction_warnings` | ✓ Implemented | Round 5 |
| R6-A | A1 project name extraction from merged-cell table layout | ✓ Implemented | Round 6 |
| R6-B | A1 `date_from`/`date_to` inversion fix across all date fields | ✓ Implemented | Round 6 |
| R6-C | Renderer empty `other_relevant_info` — closed as false positive | ✗ Closed | N/A |
| R6-D | A2 `scoring_keywords` prompt fix + soft-flag validator | ✓ Implemented | Round 6 |
| R6-E | Compressor word cap on A6 input to prevent JSON truncation | ✓ Implemented | Round 6 |
| R6-F | A4 minimum output guarantee extended to all `generative_field_keys` | ✓ Implemented | Round 6 |
| R6-G | A1 employment-only fallback — populate `relevant_projects` from `employment_record` (`description → main_project_features`) | ✓ Implemented | Round 6 |
| R7-A | A1 prompt: "References" section citations → `publications[]` | ✓ Implemented | Round 7 |
| R7-B | Post-cap chronological sort of `relevant_projects` + `countries_of_experience` at mapper write-time | ✓ Implemented | Round 7 |
| R7-C | A1 prompt: formal credentials → `certifications[]` AND `membership_professional_bodies` | ✓ Implemented | Round 7 |
| R7-D | A4 prompt: draw from `certifications[]` as KQ bullet source | ✓ Implemented | Round 7 |
| R7-E | GIZ renderer: remove education date duplication (three variants) | ✓ Implemented | Round 7 |
| R7-F | GIZ renderer: ampersand `&` escaping across all text fields | ✓ Implemented | Round 7 |
| R7-G | GIZ renderer: education rows newest-first sort | ✓ Implemented | Round 7 |
| R7-H | WB renderer: document positional `detailed_tasks` ↔ `relevant_projects` dependency; R7-B sort timing ensures correctness | ✓ Implemented | Round 7 |
| R7-I | A7: add `RENDERER_FIELD_MAP` per donor; redirect/warn on non-rendered field edits | ✓ Implemented | Round 7 |
| R7-J | Remove A4 truncation-and-restore logic (redundant with current model) | ✓ Implemented | Round 7 |
| R7-K | Remove A6 truncation entirely (silent data loss — no restoration step) | ✓ Implemented | Round 7 |
| R7-L | A6 donor-aware compression: exclude `activities_performed` for GIZ (field not rendered) | ✓ Implemented | Round 7 |
| R7-M | Transmit all pipeline warnings to frontend via API | ✓ Implemented | Round 7 |
| R7.5-A | A5 prompt: restrict style checks to `generated_fields[*].content` only | ✓ Implemented | Round 7.5 |
| R7.5-B | A4 prompt: strong preference for noun/stat-led KQ bullets; candidate-anchoring rule (both donors) | ✓ Implemented | Round 7.5 |
| R7.5-C | A3 prompt: broaden keyword scoring tolerance; raise `MIN=10`, `MAX=30` thresholds | ✓ Implemented | Round 7.5 |
| R7.5-D | A3: protect most-recent/current-role project unconditionally after cap enforcement | ✓ Implemented | Round 7.5 |
| R7.5-E | A1 prompt: degree-only routing for `education[]`; non-degree entries → `training[]` | ✓ Implemented | Round 7.5 |
| R7.5-F | A4 prompt: draw from `training[]` as additional KQ evidence source | ✓ Implemented | Round 7.5 |
| R7.5-G | R7-B bug: `countries_of_experience` sort by `date_to` descending (not `date_from`) | ✓ Implemented | Round 7.5 |
| R7.5-H | `precompute_utils.py`: `collapse_by_date_range` general utility; applied to `countries_of_experience` at mapper write-time | ✓ Implemented | Round 7.5 |
| R7.5-I | GIZ renderer: dual nationality separator `" / "` → `" and "` | ✓ Implemented | Round 7.5 |
| R8-A | A5 prompt: align style expectations with R7.5-B — noun/stat-led KQ openings are correct | ⏳ Round 8 | — |
| R8-B | A1 prompt: sharpen education routing — partial credits and certificate programmes → `training[]` | ⏳ Round 8 | — |
| R8-C | Smart 300-word cap for A3 input; 300-word cap + restoration for A4 input | ⏳ Round 8 | — |
| R8-D | CV complexity pre-screen — warn recruiter when CV exceeds size threshold | ⏳ Round 8 | — |

---

## 3. Implementation sequence

### Round 1 (completed — May 2026)
1. ✓ Fix 1 — Agent 4 model upgrade.
2. ✓ Fix 5a — Hard-block validator after Agent 4.
3. ✓ Fix 3 — CEFR centralisation at Agent 1 write time.
4. ✓ Fix 6 — Agent 7 routing surfaced via API.

### Round 2 (completed — May 2026)
5. ✓ Fix 9 — `FieldShortened.subfield` optional.
6. ✓ Fix 7 — `map_cefr` normalisation (parenthetical + numeric sentinel).
7. ✓ Fix J + Fix 8 Part 1 — Python threshold enforcement + project cap.
8. ✓ Fix 8 Part 3 — Per-project text cap in A4 pre-processing.
9. ✓ Fix 8 Part 2 — A4 prompt priority order + minimum output guarantee.

### Round 3 (completed — May 2026)
10. ✓ Fix M Part 1 — Numeric 1–5 CEFR scale mapping.
11. ✓ Fix M Part 2 — Fix 8 Part 3 truncation-text restoration.

### Round 4 (completed — May 2026)
12. ✓ R4-A — Project floor / threshold / cap constants.
13. ✓ R4-C — A4 prompt: prefer candidate's own KQ bullets.
14. ✓ R4-D — A1 prompt: route `other_skills` correctly.
15. ✓ R4-B — A1 prompt + `cefr.py`: numeric scale direction detection.
16. ✓ R4-E — Optional `references` and `certification_declaration`.

### Round 5 (completed — May 2026)
17. ✓ R5-E — A1 unfilled placeholder detection.
18. ✓ R5-A — A2 keyword extraction for Python relevance scoring.
19. ✓ R5-B — Python relevance scoring for Agent 3 + `duration` upstream.
20. ✓ R5-C — All agents to Sonnet.
21. ✓ R5-D — Soft-flag quality warnings in manifest.

### Round 6 (completed — May 2026)
22. ✓ R6-E — Compressor word cap on A6 input (hard failure fix — highest priority).
23. ✓ R6-F — A4 minimum output guarantee extended to all `generative_field_keys`.
24. ✓ R6-A — A1 project name extraction from merged-cell table layout.
25. ✓ R6-B — A1 date inversion auto-correct across all four date-field types.
26. ✓ R6-D — A2 `scoring_keywords` prompt fix + soft-flag validator.
27. ✓ R6-G — A1 employment-only fallback: `description → main_project_features`; Python safety net `_apply_employment_fallback`.

### Round 7 (completed — May 2026)
28. ✓ R7-B — Post-cap chronological sort (mapper write-time; R7-H depends on it).
29. ✓ R7-H — WB task-project pairing: document positional dependency; confirm R7-B timing.
30. ✓ R7-K — Remove A6 truncation (silent data loss — highest correctness priority).
31. ✓ R7-J — Remove A4 truncation (quality improvement; redundant with current model).
32. ✓ R7-L — A6 donor-aware compression: exclude `activities_performed` for GIZ.
33. ✓ R7-E — Education date duplication in GIZ renderer.
34. ✓ R7-F — Ampersand escaping in GIZ renderer.
35. ✓ R7-G — Education newest-first sort in GIZ renderer.
36. ✓ R7-A — A1 prompt: citations routing.
37. ✓ R7-C — A1 prompt: certifications dual-routing.
38. ✓ R7-D — A4 prompt: certifications as KQ source.
39. ✓ R7-I — A7 `RENDERER_FIELD_MAP` per donor.
40. ✓ R7-M — API warning transmission.

### Round 7.5 (completed — May 2026)
41. ✓ R7.5-D — Protect current role unconditionally after cap enforcement.
42. ✓ R7.5-G — `countries_of_experience` sort by `date_to` descending.
43. ✓ R7.5-H — `collapse_by_date_range` utility + call site in mapper.
44. ✓ R7.5-C — Broaden A3 scoring tolerance + raise MIN=10, MAX=30.
45. ✓ R7.5-I — GIZ dual nationality " and " separator.
46. ✓ R7.5-A — A5 style check scope restricted to generated fields only.
47. ✓ R7.5-B — A4 noun/stat-led KQ style + candidate-anchoring.
48. ✓ R7.5-E — A1 degree-only routing for `education[]`.
49. ✓ R7.5-F — A4 draws from `training[]` as KQ evidence source.

### Round 8 (in progress — May 2026)
50. ⏳ R8-A — A5 style alignment with R7.5-B (noun/stat-led KQ openings correct).
51. ⏳ R8-B — A1 partial credit and certificate routing sharpened.
52. ⏳ R8-C — Smart 300-word cap for A3 input; 300-word cap + restoration for A4.
53. ⏳ R8-D — CV complexity pre-screen and recruiter warning.

### Round 9 (next — pending calibration data and production runs)
54. ⏳ Fix S — Compressor word target scaled to `page_limit`; separate GIZ/WB constants (pending ≥5 calibration runs per template per page limit).
55. ⏳ R5-B threshold recalibration — review 0.30/0.40/0.50 score tier constants once R7.5-C scoring distribution stabilises.
56. ⏳ ToR caching — cache `tor_data.json` by file hash; skip A2 on repeated ToR use (infrastructure dependency).

---

## 4. Round summary

| Round | Status | Fixes delivered | Tests after round |
|-------|--------|-----------------|-------------------|
| Round 1 | ✓ Complete | Fix 1, Fix 3, Fix 5a, Fix 6 | 168/168 |
| Round 2 | ✓ Complete | Fix 9, Fix 7, Fix J, Fix 8 (Parts 1/2/3) | 277/277 |
| Round 3 | ✓ Complete | Fix M (Parts 1/2) | 294/294 |
| Round 4 | ✓ Complete | R4-A, R4-B, R4-C, R4-D, R4-E | 332/332 |
| Round 5 | ✓ Complete | R5-A, R5-B, R5-C, R5-D, R5-E | 393/393 |
| Round 6 | ✓ Complete | R6-A, R6-B, R6-C, R6-D, R6-E, R6-F, R6-G | 461/461 |
| Round 7 | ✓ Complete | R7-A, R7-B, R7-C, R7-D, R7-E, R7-F, R7-G, R7-H, R7-I, R7-J, R7-K, R7-L, R7-M (13 fixes) | — |
| Round 7.5 | ✓ Complete | R7.5-A, R7.5-B, R7.5-C, R7.5-D, R7.5-E, R7.5-F, R7.5-G, R7.5-H, R7.5-I (9 fixes) | 444/444 |
| Round 8 | ⏳ In Progress | R8-A, R8-B, R8-C, R8-D (4 fixes) | — |

Full implementation detail, file-level change tables, and production validation
results for each round are in the per-round files listed at the top of this document.

---

## 5. What this document does not cover

- **Renderer defects** — open rendering issues are tracked separately in
  `RENDERER_ISSUES.md`. This file covers two issues found during Round 7.5
  post-implementation testing: (A) `countries_of_experience` empty `date_to`
  sorts incorrectly; (B) empty `date_to` renders as trailing dash. Both are
  isolated to `countries_of_experience` handling in `giz_dynamic_template.py`
  and `cv_tor_mapper.py`. Full detail, root causes, and fix specifications are
  in `RENDERER_ISSUES.md`.
- **Fix label nomenclature** — from Round 8 onwards, fix labels follow the
  `R{round}-{letter}` scheme (e.g. R8-A, R8-B). Fixes introduced in Rounds 1–7.5
  retain their original labels (R4-A, R6-F, R7.5-B etc.) until a full rename
  script is applied. The complete mapping table (current → new label for all
  Round 4+ fixes) is in `PIPELINE_DIAGNOSTIC_ROUND_8.md`.
- World Bank renderer (`wb.py`) — examined in Round 7. `activities_performed` is
  rendered in WB output (confirmed via `wb_dynamic_template.py`). R7-L excludes
  it from GIZ compression only. R7-H documents the positional
  `detailed_tasks` ↔ `relevant_projects` pairing dependency.
- `precompute_utils.py` date parsing — `_CURRENT_YEAR` and `_CURRENT_MONTH`
  constants have been replaced with a `_current_date()` helper (using
  `datetime.date.today()`) so "Present" durations and year ranges are always
  computed against the real current date. Tests updated to match.
- Embedding-based semantic scoring for R5-B — documented in
  `RELEVANCE_SCORING_DESIGN.md` as a future dependency on an embedding API.
- Concurrency under multiple simultaneous sessions — the manifest lock registry
  in `manifest.py` handles Phase 1 parallelism but has not been tested under
  high session concurrency.
- `TARGET_WORDS_PER_PAGE` calibration for Fix S — requires a minimum of 5 clean
  rendered output `.docx` files across GIZ and WB templates at different page
  limits. Separate GIZ and WB constants are needed — Run 6 Round 8 validation
  confirms WB 4-page target of 1,800 is too low (actual post-compression: 2,108
  words). Process and expected constants documented in
  `COMPRESSION_CALIBRATION_CONTEXT.md`. Cannot be implemented until sufficient
  production data is available.

---

## 6. Ongoing rounds and iterative scope

The fix rounds documented in this file are not a finite list with a predetermined
end point. Each round follows the same cycle: implement fixes, run production
validation against real CVs and ToRs, and surface new issues from the results.
The issues found during testing in each round directly define the scope of the
next round.

Rounds 1 through 3 progressed from critical pipeline failures (empty generated
fields, broken threshold enforcement, truncation leaks) toward quality and
completeness issues (project over-dropping, CEFR scale direction, KQ style,
field routing). This reflects the pipeline stabilising over time, but does not
mean the scope is closed. Each new CV format, ToR type, or candidate profile
encountered in production testing is a potential source of new edge cases.

Some fixes introduced in earlier rounds are explicitly interim. R4-A's threshold
and cap constants are calibration values that will need revisiting once R5-B
(Python relevance scoring) produces consistent scores. R4-B's scale-direction
inference is heuristic-based and is expected to encounter edge cases in CVs with
non-standard or ambiguous language table headers. R4-C's prompt guidance to A4
will need validation across a wider range of KQ styles before it can be considered
stable.

This document and the per-round files should be updated at the end of every round
— new issues added to Section 1, new fixes to Section 2, the implementation
sequence in Section 3 updated, the round summary table in Section 4 updated, and
the relevant round file extended with test results and production validation findings.
