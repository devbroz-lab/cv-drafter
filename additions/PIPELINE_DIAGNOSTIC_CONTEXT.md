# Pipeline Diagnostic Context — Agent Quality & Data Flow Issues

**Date**: May 2026
**Scope**: Full pipeline review covering Agents 1–7, the GIZ renderer, and supporting
infrastructure. Based on live session artifacts (`cv_data.json`, `mapped_cv.json`,
`generated_fields.json`, `output.docx`) alongside all agent source files and the
renderer.

**Implementation status** (as of Round 7 — May 2026): Fixes 1, 3, 5a, 6, 7,
8 (Parts 1/2/3), 9, Fix J, Fix M (Parts 1 and 2), Round 4 fixes (N, O, P, Q, R),
Round 5 fixes (U, 4b, 4, 2, 5b), Round 6 fixes (V, W, Y, Z, AA), and Round 7
fix (CC — employment fallback field mapping) are implemented.
Fix S and Fix 4 threshold recalibration remain deferred to Round 8.

Cross-reference with: `PIPELINE_CONTEXT.md`, `RENDERER_CONTEXT.md`,
`PROMPT_REVIEW_CONTEXT.md`, `PROMPT_REVIEW_IMPLEMENTATION.md`,
`RUNS_ARTIFACTS_CONTEXT.md`, `RELEVANCE_SCORING_DESIGN.md`.

Round-by-round implementation records:
- `PIPELINE_DIAGNOSTIC_ROUND_1.md`
- `PIPELINE_DIAGNOSTIC_ROUND_2.md`
- `PIPELINE_DIAGNOSTIC_ROUND_3.md`
- `PIPELINE_DIAGNOSTIC_ROUND_4.md`
- `PIPELINE_DIAGNOSTIC_ROUND_5.md`
- `PIPELINE_DIAGNOSTIC_ROUND_6.md`

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

### Issue C — Relevance scoring delegated to LLM arithmetic (consistency risk) — **PENDING (Fix 4)**

**What was observed**: Agent 3's scoring is entirely LLM-side. The system prompt
specifies a four-dimensional weighted scoring model (sector keywords 35%, key
tasks 30%, competencies 20%, geography 15%) and asks the LLM to assign scores
and make keep/drop decisions. LLMs are inconsistent at weighted arithmetic across
sessions. The `_precompute_relevance_scores` stub currently returns `None`.

**Additional observation**: The `duration` pre-compute runs inside
`fields_generator.py` — after A3 has already scored and filtered projects.
A3's LLM therefore scores projects with no `duration` field populated.

---

### Issue D — No semantic validation between pipeline stages — **PARTIALLY FIXED (Fix 5a implemented; Fix 5b pending)**

**What was observed**: `manifest.py` `done` status means only that the agent
completed without raising a Python exception. No check exists that output is
semantically useful.

**Partial resolution (Fix 5a)**: The A4→A5 hard-block gap is now closed by
`validate_fields_generator_output` in `pipeline/validators.py`. Remaining gaps
(A5→A6 review block check, A6→renderer compression check) and soft-flag warnings
are deferred as Fix 5b. See `PIPELINE_DIAGNOSTIC_ROUND_1.md`.

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

### Issue N — Agent 3 project floor too low; cap too aggressive (over-dropping) — **PENDING (Fix N)**

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

Constants should be treated as interim values pending Fix 4. See
`PIPELINE_DIAGNOSTIC_ROUND_3.md` for full artifact evidence.

---

### Issue O — `map_cefr` numeric scale direction assumed fixed (1=C1) — **PENDING (Fix O)**

**What was observed**: Round 3 Run 4 source CV states `"1 – excellent; 5 – basic"`,
meaning `1 = C2`. Fix M Part 1 mapped `1 → C1`, producing the wrong level. A1
correctly flagged the ambiguity in `extraction_warnings` but the hard-coded
mapping overrode it.

**Recommended fix**: A1 emits `language_scale_direction` (`"1_best"` / `"1_worst"`
/ `null`). `_populate_cefr_fields` inverts the mapping when `"1_best"` is detected:
`1→C2, 2→C1, 3→B2, 4→B1, 5→A2`.

---

### Issue P — Agent 4 synthesises new KQ bullets instead of condensing candidate's own text — **PENDING (Fix P)**

**What was observed**: Round 3 Run 4 — A1 correctly extracted 9 bullet-style
`key_qualifications` matching the expected output style. A4 discarded them and
generated new thematic bullets instead.

**Recommended fix**: Add preference instruction to `SYSTEM_PROMPT_A4` — when
`key_qualifications` contains bullet-format entries reasonably aligned with the
ToR, prefer selecting and lightly editing those over generating from scratch.

---

### Issue Q — `other_skills` field not populated; certifications data not routed correctly — **PENDING (Fix Q)**

**What was observed**: Round 3 Run 4 — source CV has a "Other skills" section.
A1 routed its content to `certifications[]` but left `other_skills: []` empty.
The renderer reads `other_skills`, so the section renders blank.

**Recommended fix**: Update A1's prompt to populate `other_skills` from content
explicitly labelled "Other skills" in the source document.

---

### Issue R — `references` and `certification_declaration` fields absent from A1 schema — **PENDING (Fix R)**

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

### Issue U — A1 extracts unfilled placeholder text verbatim — **FIXED (Fix U)**

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

### Issue V — A1 fails to extract `project_name` and details from merged-cell table layout — **FIXED (Fix V)**

**What was observed**: Round 5 Run 4 — 11 of 24 projects had blank `project_name`
and empty detail fields. Source CV uses a two-column table with merged cells where
the left column contains project title and dates. A1 created correct entry count
but failed to map the title to `project_name`.

**Recommended fix**: Extend A1's prompt to explicitly extract `project_name` from
the left/title column of two-column project tables regardless of cell merge formatting.

---

### Issue W — A1 inverts `date_from` / `date_to` for `countries_of_experience` — **FIXED (Fix W)**

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

### Issue Y — A2 produces empty `scoring_keywords` despite rich ToR content — **FIXED (Fix Y)**

**What was observed**: Round 5 Run 4 — all three `scoring_keywords` lists empty
despite a 36-page PDF ToR with explicit requirements. Fix 4's Python scorer had
no keywords, producing near-uniform scores (0.20–0.28). Round 5 Run 5 confirmed
Fix 4b working correctly on a non-PDF ToR — all keyword lists fully populated.

**Root cause**: A2's keyword extraction section not firing on PDF-sourced content,
or being deprioritised on long inputs. PDF-specific issue.

**Recommended fix**: Move scoring keywords instruction earlier in `SYSTEM_PROMPT_A2`;
add `generation_warnings` entry when all lists are empty.

---

### Issue Z — Compressor JSON truncation on large input — **FIXED (Fix Z)**

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

### Issue CC — `relevant_projects` empty for employment-only format CVs — **FIXED (Fix CC)**

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

### Issue AA — A4 `detailed_tasks` empty on geographic mismatch (WB format) — **FIXED (Fix AA)**

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
| Fix 2 | Upgrade all remaining agents to Sonnet | ✓ Implemented | Round 5 |
| Fix 3 | Centralise CEFR mapping at Agent 1 write time | ✓ Implemented | Round 1 |
| Fix 4 | Python relevance scoring for Agent 3 + duration upstream | ✓ Implemented | Round 5 |
| Fix 5a | Hard-block validator after Agent 4 | ✓ Implemented | Round 1 |
| Fix 5b | Soft-flag quality warnings in manifest | ✓ Implemented | Round 5 |
| Fix 6 | Surface Agent 7 routing decision via API | ✓ Implemented | Round 1 |
| Fix 7 | `map_cefr` normalisation (parenthetical + numeric sentinel) | ✓ Implemented | Round 2 |
| Fix 8 Part 1 | Hard project cap (`MAX_PROJECTS_TO_KEEP = 6`) | ✓ Implemented | Round 2 |
| Fix 8 Part 2 | A4 prompt priority order + minimum output guarantee | ✓ Implemented | Round 2 |
| Fix 8 Part 3 | Per-project text cap in A4 pre-processing | ✓ Implemented | Round 2 |
| Fix 9 | `FieldShortened.subfield` optional | ✓ Implemented | Round 2 |
| Fix J | Python threshold enforcement for Agent 3 | ✓ Implemented | Round 2 |
| Fix M Part 1 | Numeric 1–5 CEFR scale mapping | ✓ Implemented | Round 3 |
| Fix M Part 2 | Fix 8 Part 3 truncation-text restoration | ✓ Implemented | Round 3 |
| Fix N | Raise floor, lower thresholds, raise cap | ✓ Implemented | Round 4 |
| Fix O | Numeric CEFR scale direction detection | ✓ Implemented | Round 4 |
| Fix P | A4 prompt: prefer candidate's own KQ bullets | ✓ Implemented | Round 4 |
| Fix Q | A1 prompt: route `other_skills` correctly | ✓ Implemented | Round 4 |
| Fix R | Optional `references` and `certification_declaration` | ✓ Implemented | Round 4 |
| Fix 4b | A2 keyword extraction for Python relevance scoring | ✓ Implemented | Round 5 |
| Fix S | Compressor word target scaled to `page_limit` | ⏳ Deferred | Round 7 |
| Fix U | A1 unfilled placeholder detection in `extraction_warnings` | ✓ Implemented | Round 5 |
| Fix V | A1 project name extraction from merged-cell table layout | ✓ Implemented | Round 6 |
| Fix W | A1 `date_from`/`date_to` inversion fix across all date fields | ✓ Implemented | Round 6 |
| Fix X | Renderer empty `other_relevant_info` — closed as false positive | ✗ Closed | N/A |
| Fix Y | A2 `scoring_keywords` prompt fix + soft-flag validator | ✓ Implemented | Round 6 |
| Fix Z | Compressor word cap on A6 input to prevent JSON truncation | ✓ Implemented | Round 6 |
| Fix AA | A4 minimum output guarantee extended to all `generative_field_keys` | ✓ Implemented | Round 6 |
| Fix CC | A1 employment-only fallback — populate `relevant_projects` from `employment_record` (`description → main_project_features`) | ✓ Implemented | Round 7 |

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
12. ✓ Fix N — Project floor / threshold / cap constants.
13. ✓ Fix P — A4 prompt: prefer candidate's own KQ bullets.
14. ✓ Fix Q — A1 prompt: route `other_skills` correctly.
15. ✓ Fix O — A1 prompt + `cefr.py`: numeric scale direction detection.
16. ✓ Fix R — Optional `references` and `certification_declaration`.

### Round 5 (completed — May 2026)
17. ✓ Fix U — A1 unfilled placeholder detection.
18. ✓ Fix 4b — A2 keyword extraction for Python relevance scoring.
19. ✓ Fix 4 — Python relevance scoring for Agent 3 + `duration` upstream.
20. ✓ Fix 2 — All agents to Sonnet.
21. ✓ Fix 5b — Soft-flag quality warnings in manifest.

### Round 6 (completed — May 2026)
22. ✓ Fix Z — Compressor word cap on A6 input (hard failure fix — highest priority).
23. ✓ Fix AA — A4 minimum output guarantee extended to all `generative_field_keys`.
24. ✓ Fix V — A1 project name extraction from merged-cell table layout.
25. ✓ Fix W — A1 date inversion auto-correct across all four date-field types.
26. ✓ Fix Y — A2 `scoring_keywords` prompt fix + soft-flag validator.

### Round 7 (completed — May 2026)
27. ✓ Fix CC — A1 employment-only fallback: `description → main_project_features`; Python safety net `_apply_employment_fallback`.

### Round 8 (next)
28. ⏳ Fix S — Compressor word target scaled to `page_limit` (pending calibration data).
29. ⏳ Fix 4 threshold recalibration — review MIN/MAX constants once Fix 4 scoring distribution is stable.

---

## 4. Round summary

| Round | Status | Fixes delivered | Tests after round |
|-------|--------|-----------------|-------------------|
| Round 1 | ✓ Complete | Fix 1, Fix 3, Fix 5a, Fix 6 | 168/168 |
| Round 2 | ✓ Complete | Fix 9, Fix 7, Fix J, Fix 8 (Parts 1/2/3) | 277/277 |
| Round 3 | ✓ Complete | Fix M (Parts 1/2) | 294/294 |
| Round 4 | ✓ Complete | Fix N, P, Q, O, R | 332/332 |
| Round 5 | ✓ Complete | Fix U, Fix 4b, Fix 4, Fix 2, Fix 5b | 393/393 |
| Round 6 | ✓ Complete | Fix Z, AA, V, W, Y | 421/421 |
| Round 7 | ✓ Complete | Fix CC (employment fallback field mapping) | 461/461 |
| Round 8 | ⏳ Pending | Fix S, Fix 4 threshold recalibration | — |

Full implementation detail, file-level change tables, and production validation
results for each round are in the per-round files listed at the top of this document.

---

## 5. What this document does not cover

- World Bank renderer (`wb.py`) — not examined in this review. Assume analogous
  issues exist in `_build_context` for the WB format, particularly around
  `detailed_tasks` and `employment_record`.
- `precompute_utils.py` date parsing — `_CURRENT_YEAR` and `_CURRENT_MONTH`
  constants have been replaced with a `_current_date()` helper (using
  `datetime.date.today()`) so "Present" durations and year ranges are always
  computed against the real current date. Tests updated to match.
- Embedding-based semantic scoring for Fix 4 — documented in
  `RELEVANCE_SCORING_DESIGN.md` as a future dependency on an embedding API.
- Concurrency under multiple simultaneous sessions — the manifest lock registry
  in `manifest.py` handles Phase 1 parallelism but has not been tested under
  high session concurrency.
- `TARGET_WORDS_PER_PAGE` calibration for Fix S — requires a minimum of 5 clean
  rendered output `.docx` files across GIZ and WB templates at different page
  limits. Process and expected constants documented in
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

Some fixes introduced in earlier rounds are explicitly interim. Fix N's threshold
and cap constants are calibration values that will need revisiting once Fix 4
(Python relevance scoring) produces consistent scores. Fix O's scale-direction
inference is heuristic-based and is expected to encounter edge cases in CVs with
non-standard or ambiguous language table headers. Fix P's prompt guidance to A4
will need validation across a wider range of KQ styles before it can be considered
stable.

This document and the per-round files should be updated at the end of every round
— new issues added to Section 1, new fixes to Section 2, the implementation
sequence in Section 3 updated, the round summary table in Section 4 updated, and
the relevant round file extended with test results and production validation findings.
