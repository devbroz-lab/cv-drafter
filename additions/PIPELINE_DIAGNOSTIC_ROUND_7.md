# Pipeline Diagnostic — Round 7 Implementation Record

**Date**: May 2026
**Status**: ✅ Complete
**Tests after round**: —

---

## Fixes delivered

| Fix | File(s) changed | Summary |
|-----|----------------|---------|
| DD | `pipeline/agents/cv_extractor.py` | Added citation-routing rule: "References" sections with citations → `publications[]`, not `references[]` |
| EE | `pipeline/agents/cv_tor_mapper.py` | Post-cap sort of `relevant_projects` + `countries_of_experience` newest-first at mapper write-time |
| FF-A | `pipeline/agents/cv_extractor.py` | Certifications dual-routing: formal engineering credentials → both `certifications[]` and `membership_professional_bodies` |
| FF-B | `pipeline/agents/fields_generator.py` | Added `certifications[]` as eligible KQ evidence source in `SYSTEM_PROMPT_A4` |
| GG | `templates/giz.py` | Removed `[date_range]` suffix from institution cell; single-year diplomas now write `date_obtained` into `date_from` |
| HH | `templates/giz.py` | Added `_xml_str()` helper applying `html.escape()` to all string values in `_build_context`; `import html` added |
| II-A | `templates/wb.py` | Added comment documenting positional dependency on Fix EE sort order |
| II-B | `pipeline/agents/field_editor.py` | Added `RENDERER_FIELD_MAP` per donor; `_check_renderer_field()` redirects/skips non-rendered field edits before Claude call; `SYSTEM_PROMPT_A7` note added |
| JJ | `pipeline/agents/fields_generator.py` | Removed `_truncate_project_text_for_a4`, `_restore_truncated_project_text`, `A4_INPUT_PROJECT_WORD_CAP`, `_A4_CAPPED_FIELDS`; A4 receives full project text |
| KK | `pipeline/agents/compressor.py` | Removed `_truncate_project_text_for_a6`, `A6_INPUT_PROJECT_WORD_CAP`, `_A6_CAPPED_FIELDS`, `import copy`, and all `input_field_truncated` warning emits |
| LL | `pipeline/agents/compressor.py` | Donor-aware A6 compression: GIZ runs strip `activities_performed` before A6, restore originals after; `SYSTEM_PROMPT_A6` donor note added |
| MM | `api/routers/sessions.py`, `api/models/requests.py` | Added `GET /sessions/{id}/warnings` endpoint; added `WarningEntry` and `WarningsResponse` models; aggregates warnings from all four pipeline stages |
| R7-5 | `templates/giz.py` | Education list sorted newest-first using `_parse_date` + `_edu_date_sort_key` before building rows |

---

## Deferred from Round 6

### Fix S — Compressor word target scaled to `page_limit`
Pending calibration data (5+ clean rendered outputs per template at different
page limits). Round 7 production runs provide the following data points:

| Run | Donor | Page limit | Projects kept | Words (post-compression) | Compressor fired? |
|-----|-------|-----------|---------------|--------------------------|-------------------|
| Run 1 | GIZ | 4 | 5 | 1,108 | No |
| Run 2 | GIZ | 4 | 5 | 460 | No |
| Run 3 | GIZ | 2 | 10 | 848 | Yes (1,221 → 848) |
| Run 4 | GIZ | 4 | 7 | 1,277 | No |
| Run 5 | GIZ | 4 | 5 | 762 | No |
| Run 6 | WB  | 4 | 5 | 1,433 | No |
| Run 7 | WB  | 4 | 5 | 1,187 | No |

**Observations**: All four 4-page GIZ runs came in under 1,800-word target without
compression. The current `TARGET_WORDS_PER_PAGE = 450` yields a 4-page target of
1,800, which is consistently too generous. Run 3 confirms the 2-page target of 900
is approximately correct (848 words post-compression). More data needed before
recalibrating the constant.

### Fix 4 threshold recalibration
Review `MIN_PROJECTS_TO_KEEP` and `MAX_PROJECTS_TO_KEEP` constants once Fix 4
scoring distribution stabilises. Round 7 runs confirm scoring is working as
intended. No recalibration indicated yet — floor-guarantee activations in Runs 1,
5, 7 are correct pipeline behaviour for genuinely misaligned candidates, not a
threshold miscalibration signal.

---

## Issues identified in Round 7 production validation

### Issue R7-1 — All-projects-below-threshold: quality signal breaks down (observation)
When all projects score below the relevance threshold and the floor guarantee
activates, A4 generates against a fundamentally misaligned CV. The pipeline
handles this correctly (generates best available, flags heavily, blocks at
reviewer), but the output is a polished set of hedged bullets for a candidate
who does not meet the ToR requirements. No pipeline fix needed — correct
behaviour. Recorded for awareness.

### Issue R7-2 — Lexical keyword scorer misses regional-to-national overlap (observation)
SAEP Outcome 3 project (regional transmission, SAPP, Southern Africa) scored 0.20
against a South Africa-specific ToR because the CV uses "Southern Africa / SAPP"
language rather than "South Africa". The work is directly SA-relevant but the
lexical keyword scorer cannot detect it. Known limitation of lexical matching vs
semantic matching. Tied to the embedding-based Fix 4 scoring path (deferred).
Recorded for awareness.

### Issue R7-3 — CLOSED
Empty `activities_performed` on WB-format CVs suspected to impair A3 keyword
scoring. Confirmed not a bug after reading `precompute_utils.py`:
`keyword_overlap_score` already concatenates all four fields including
`main_project_features`. Low scores in Run 2 were genuinely poor keyword matches,
not scoring impairment. No fix needed.

### Issue R7-4 — Placeholder KQ entries reaching A4: keep-and-warn confirmed (observation)
Source CVs with unfilled template placeholders in `key_qualifications` (e.g.
"X years of experience in [mention area]") pass through A1 with a warning and
reach A4 as source material. A4 correctly works around them and emits generation
warnings. Decision: keep-and-warn behaviour is correct — information is preserved
and the LLM is tolerant of partial placeholder content. No fix needed.

---

## Fixes identified in Round 7

### Fix DD — A1 prompt: "References" section (citations) → `publications`

**Problem**: Source CVs with a section labelled "References" containing academic
citations (not contact references) may be routed to the structured `references[]`
field (people/contacts) rather than `publications[]`. The two section labels share
a name but have different content types.

**Scope**: `SYSTEM_PROMPT_A1` in `pipeline/agents/cv_extractor.py`. Prompt-only.

**Planned change**: Add explicit routing rule: a section labelled "References",
"Reference List", or similar containing citations (author, title, journal/
conference, year) must be routed to `publications[]`. The structured `references[]`
field (schema: name, title, organisation, email, phone) is reserved for contact
references only — i.e. named individuals with contact details.

---

### Fix EE — Post-cap chronological sort of `relevant_projects` and `countries_of_experience`

**Problem**: After A3's threshold/cap enforcement, kept projects are returned in
score-rank order, not chronological order. The renderer renders them in whatever
order they arrive. Runs 1–5 confirmed the output order is by relevance score, not
by date. GIZ CVs conventionally list projects newest-first.

**Scope**: `pipeline/agents/cv_tor_mapper.py` — Python post-processing after
`_enforce_threshold_and_cap`. Also applies to `countries_of_experience`.

**Planned change**: After the final kept list is determined, sort
`relevant_projects` descending by `date_from` using `_parse_date_to_months` from
`precompute_utils.py` as the sort key. Apply the same sort to
`countries_of_experience`. "Present" always sorts later than any literal date
(already handled by `_parse_date` returning `_current_date()` for present values).

---

### Fix FF-A — A1 prompt: certifications routing to both `certifications[]` and `membership_professional_bodies`

**Problem**: Professional credentials such as "Eur Ing" and "C Eng" are being
routed exclusively to `membership_professional_bodies` rather than also being
captured in `certifications[]`. Confirmed in Run 2 (Hadjicostas): `certifications:
[]` despite clear credentials in source CV.

**Scope**: `SYSTEM_PROMPT_A1` in `pipeline/agents/cv_extractor.py`. Prompt-only.

**Planned change**: Add instruction that formal professional credentials and
chartered/registered engineering designations (e.g. Eur Ing, C Eng, PE, CEng,
PEng, Pr Eng) should be written to **both** `certifications[]` (as a structured
entry) and retained in `membership_professional_bodies` (as free text). The two
fields serve different downstream purposes: `certifications[]` feeds A4 generation;
`membership_professional_bodies` feeds the renderer directly.

---

### Fix FF-B — A4 prompt: draw from `certifications[]` as source for KQ bullets

**Problem**: A4's KQ generation prompt does not instruct it to draw from
`certifications[]` as eligible source material. Certifications (formal credentials,
chartered designations) are directly relevant to ToR competency requirements and
should inform KQ bullets.

**Scope**: `SYSTEM_PROMPT_A4` in `pipeline/agents/fields_generator.py`.
Prompt-only.

**Planned change**: Add `certifications[]` to the list of CV evidence sources A4
may draw from when generating KQ bullets. Specifically: if a `certifications[]`
entry matches a ToR `required_competency`, it may ground a KQ bullet with
`source="experience"`.

---

### Fix GG — Education date duplication in GIZ renderer

**Problem**: Education rows in Table 1 of the GIZ output show the date range
twice: once from the static `[DATE FROM – DATE TO]` label baked into the template
cell, and once from the actual `date_from`/`date_to` values written by the
renderer. Confirmed across Runs 1, 2, 3, 5.

Three variants observed:
- Standard: `University of X [2010 – 2014]\n2010 – 2014`
- Missing `date_from`: `[September 2010 – October 2010]\nSeptember 2010`
- Single-year: `[1976]\n -`

**Root cause**: `_build_context` in `giz.py` constructs the `institution` cell
value as `f"{institution} [{date_range}]"` and also passes `date_from` and
`date_to` as separate keys. The dynamic template writes both into the same cell,
producing the duplication.

**Scope**: `templates/giz.py` — `_build_context` education section. Python-only.

**Planned change**: Remove the `[{date_range}]` suffix from the `institution`
string in `_build_context`. The date range is already rendered via the separate
`date_from` / `date_to` template variables. The institution cell should contain
only the institution name.

---

### Fix HH — Ampersand `&` stripping across all text fields in GIZ renderer

**Problem**: Ampersand characters in field values are being stripped (rendered as
a double space) in the GIZ output. Confirmed across Runs 3 and 5: "Legal & Policy"
→ "Legal  Policy", "Mineral Resources & Energy" → "Mineral Resources  Energy",
"NREL & Berkeley Lab" → "NREL  Berkeley Lab".

**Root cause**: In docx XML, `&` must be escaped as `&amp;`. If the renderer
writes raw `&` characters into XML cells without escaping, the XML parser strips
them. `docxtpl` handles this for Jinja2-rendered values, but any value constructed
manually (e.g. string concatenation in `_build_context`) bypasses this escaping.

**Scope**: `templates/giz.py` — `_build_context` all text field construction.
Python-only.

**Planned change**: Audit all string construction in `_build_context` that
concatenates or joins values. Ensure any field value containing `&` passes through
`docxtpl`'s Jinja2 rendering path (i.e. is placed in the context dict and rendered
via `{{ variable }}`) rather than being embedded as raw XML. Alternatively, apply
`html.escape()` to all manually-constructed strings before inserting into context.

---

### Fix R7-5 — Education rows not sorted newest-first in GIZ renderer

**Problem**: Education entries in the GIZ output Table 1 are rendered in source CV
order, which may be oldest-first. GIZ CV convention is newest-first (most recent
qualification at the top).

**Scope**: `templates/giz.py` — `_build_context` education section. Python-only.

**Planned change**: Sort the `education` list descending by `date_to` (falling
back to `date_from` if `date_to` is empty) before building education rows.
Use `_parse_date_to_months` from `precompute_utils.py` for consistent parsing.

---

### Fix II-A — WB renderer: make `detailed_tasks` ↔ `relevant_projects` pairing explicit

**Problem**: In `wb.py` `_build_context`, `detailed_tasks[i]` is paired to
`relevant_projects[i]` by pure list position:
`"tasks_assigned": detailed_tasks[i] if i < len(detailed_tasks) else ""`.
Fix EE will re-sort `relevant_projects` by date after alignment. If project order
changes between A4 generation (which produces `detailed_tasks` indexed to the
pre-sort order) and the renderer (which renders against the post-sort order), task
statements will appear next to the wrong projects in the WB output.

**Scope**: `templates/wb.py` — `_build_context` relevant_projects section.
Python-only.

**Planned change**: Fix EE should be applied *before* A4 runs (i.e. in
`cv_tor_mapper.py` so `mapped_cv.json` already has projects in sorted order). This
ensures A4 generates `detailed_tasks` in the same order the renderer will render
projects. The positional pairing in `wb.py` then remains correct. The fix is
therefore in the *timing* of Fix EE (sort happens at mapper write-time, not
renderer read-time), not in the renderer itself. Add an explicit comment in `wb.py`
documenting the positional dependency.

---

### Fix II-B — A7: add `RENDERER_FIELD_MAP` per donor

**Problem**: A7 operates on the data model but has no visibility into which fields
are actually rendered in the output document. Specifically:

- For GIZ: `activities_performed` is passed to the template context by `giz.py`
  but is never placed in any cell by `giz_dynamic_template.py`. A7 editing
  `relevant_projects[i].activities_performed` on a GIZ run writes correctly to
  `generated_fields.json` but produces no visible change in the output `.docx`.
- For WB: `activities_performed` is rendered (confirmed in `wb_dynamic_template.py`).

A7 currently has no way to detect or warn about this discrepancy.

**Scope**: `pipeline/agents/field_editor.py`. Python + minor prompt addition.

**Planned change**:
- Add a `RENDERER_FIELD_MAP` constant dict keyed by donor format, listing which
  project-level field paths are rendered vs not rendered.
- Before calling Claude, check if the target field path resolves to a non-rendered
  field for the current donor. If so: either redirect the edit to the nearest
  rendered equivalent (e.g. `activities_performed` → `main_project_features` for
  GIZ), or skip with a clear reason explaining the field is not rendered in GIZ
  output.
- Add a brief note to `SYSTEM_PROMPT_A7` clarifying that field paths are
  donor-aware and some fields may be redirected.

---

### Fix JJ — Remove A4 truncation-and-restore logic

**Problem**: `_truncate_project_text_for_a4` caps `activities_performed` and
`main_project_features` to 150 words per project in A4's input. This was
introduced to prevent token exhaustion. The current model (`claude-sonnet-4-6`,
formerly `claude-sonnet-4-20250514`) has a 200k token context window and handles
dense CV inputs without risk of truncation. The restoration step
(`_restore_truncated_project_text`) works correctly and protects the artifact, but
the truncation is unnecessary and limits A4's grounding quality — it generates KQ
bullets and detailed tasks from a reduced view of each project.

**Scope**: `pipeline/agents/fields_generator.py`. Python-only.

**Planned change**: Remove `_truncate_project_text_for_a4`,
`_restore_truncated_project_text`, `A4_INPUT_PROJECT_WORD_CAP`,
`_A4_CAPPED_FIELDS`, and the associated `cv_data_full` preservation step from
`run()`. A4 receives full project text directly. Simplifies `run()` by ~30 lines.

---

### Fix KK — Remove A6 truncation (silent data loss)

**Problem**: `_truncate_project_text_for_a6` caps project text to 150 words per
field before A6's input. Unlike Fix 8 Part 3 / Fix M Part 2 for A4, **there is no
restoration step** — the comment in the code explicitly states this is intentional
("A6 is explicitly compressing these fields anyway"). This is incorrect: A6 is
supposed to make intelligent compression decisions proportionally across all fields.
If it only sees 150 words of a 694-word `activities_performed` (Run 6, BADGE
project), it compresses the truncated version and writes that back. The remaining
544 words are permanently lost — not compressed, silently dropped.

Additionally, the compressor's `max_tokens=16000` constraint is on the *output*
side (A6 writes a compressed, shorter version of the input), not the input side.
There is no token exhaustion risk from receiving full project text on
`claude-sonnet-4-6`.

**Scope**: `pipeline/agents/compressor.py`. Python-only.

**Planned change**: Remove `_truncate_project_text_for_a6`,
`A6_INPUT_PROJECT_WORD_CAP`, `_A6_CAPPED_FIELDS`, the call site in `run()`, and
the associated `append_warning` calls for truncation events. A6 receives full
untruncated project text. This eliminates the `input_field_truncated` manifest
warning type entirely.

---

### Fix LL — A6 donor-aware compression: exclude `activities_performed` for GIZ

**Problem**: The GIZ renderer (`giz.py` + `giz_dynamic_template.py`) never renders
`activities_performed` in the output document — the field is passed to the template
context but is not placed in any table cell. A6 currently compresses
`activities_performed` uniformly for both GIZ and WB donors. For GIZ runs, this
compression has zero effect on the rendered output and wastes A6's compression
budget on a field that does not appear.

WB renderer (`wb_dynamic_template.py`) does render `activities_performed`, so
compression is appropriate for WB runs.

**Scope**: `SYSTEM_PROMPT_A6` in `pipeline/agents/compressor.py` + `run()` Python
logic. Prompt + Python.

**Planned change**:
- Pass the donor format into A6's compression params (already available in
  `manifest.params.donor`).
- Add a donor-aware exclusion in `SYSTEM_PROMPT_A6`: for GIZ runs, exclude
  `activities_performed` from the compressible field set.
- Update `count_words_per_field` call or add a pre-filter in `run()` to exclude
  `activities_performed` from the `words_per_field` dict for GIZ runs, so the
  word count arithmetic is accurate and A6 doesn't attempt to compress the field.

---

### Fix MM — Transmit all pipeline warnings through the API to the frontend

**Problem**: The following warning types are written to disk correctly but never
transmitted to the frontend via any API endpoint:

- `cv_data.json → extraction_warnings[]` — A1 extraction issues (date inversions,
  placeholder text, merged cells, fallback activations).
- `mapped_cv.json → alignment.warnings[]` — A3 scoring issues (threshold
  activations, geography mismatches, high drop rates).
- `manifest.json → warnings[]` — orchestrator-level warnings (`high_severity_count_unusual`,
  `input_field_truncated`, `generation_warnings_high`, `applied_false`).

Currently only `generated_fields.json → generation_warnings[]`,
`review.high_severity[]`, and `review.low_severity[]` reach the frontend via
`GET /sessions/{id}/review` and `GET /sessions/{id}/output`.

**Scope**: `api/routers/sessions.py`. Python-only.

**Planned change**: Extend the relevant API response models and endpoint handlers
to include all warning types. Suggested approach: add a unified
`GET /sessions/{id}/warnings` endpoint that aggregates warnings from all four
sources into a single response, tagged by stage and kind. Alternatively, extend
`SessionStatusResponse` or `OutputResponse` with a `warnings` array. Display vs
abstraction decisions are left entirely to the UI developer.

---

## Files to be changed

| File | Planned change |
|------|---------------|
| `pipeline/agents/cv_extractor.py` | Fix DD: citations routing rule; Fix FF-A: certifications dual-routing |
| `pipeline/agents/cv_tor_mapper.py` | Fix EE: post-cap sort of `relevant_projects` + `countries_of_experience` (sort at write-time so A4 sees sorted order) |
| `pipeline/agents/fields_generator.py` | Fix FF-B: `certifications[]` as KQ source; Fix JJ: remove truncation-and-restore logic |
| `pipeline/agents/compressor.py` | Fix KK: remove A6 truncation; Fix LL: donor-aware `activities_performed` exclusion for GIZ |
| `templates/giz.py` | Fix GG: remove `[date_range]` from institution string; Fix HH: ampersand escaping; Fix R7-5: education newest-first sort |
| `templates/wb.py` | Fix II-A: document positional dependency; confirm sort timing with Fix EE |
| `pipeline/agents/field_editor.py` | Fix II-B: `RENDERER_FIELD_MAP` per donor; redirect/warn on non-rendered fields |
| `api/routers/sessions.py` | Fix MM: transmit all warning types to frontend |

---

## Implementation sequence

Priority order for Round 7:

1. Fix EE — chronological sort in mapper (foundational — Fix II-A depends on it)
2. Fix II-A — confirm WB task-project pairing after Fix EE
3. Fix KK — remove A6 truncation (silent data loss — highest correctness priority)
4. Fix JJ — remove A4 truncation (quality improvement)
5. Fix LL — donor-aware compression for GIZ (correctness + efficiency)
6. Fix GG — education date duplication (renderer correctness)
7. Fix HH — ampersand escaping (renderer correctness)
8. Fix R7-5 — education newest-first sort (renderer convention)
9. Fix DD — A1 citations routing (prompt)
10. Fix FF-A — A1 certifications dual-routing (prompt)
11. Fix FF-B — A4 certifications as KQ source (prompt)
12. Fix II-B — A7 `RENDERER_FIELD_MAP` (A7 sync)
13. Fix MM — API warning transmission (observability)

---

## Design decisions

1. **Fix EE timing**: Sort applied at `cv_tor_mapper.py` write-time (to
   `mapped_cv.json`), not at render time. This ensures A4 generates `detailed_tasks`
   in the same order as the renderer will display projects, keeping the WB
   positional pairing correct without changes to `wb.py`.

2. **Fix II-A**: No change to WB renderer pairing logic. The fix is ensuring Fix
   EE sorts before A4 runs, so the positional coupling is never broken.

3. **Fix JJ + Fix KK**: Both truncation mechanisms removed entirely. The 150-word
   cap was introduced when smaller models were in use. `claude-sonnet-4-6`'s 200k
   context window makes it unnecessary. For A4, the restoration step was working
   correctly but is now redundant. For A6, the lack of restoration was causing
   silent permanent data loss.

4. **Fix LL**: `activities_performed` is not rendered by the GIZ template. A6
   compressing it wastes budget. Exclusion is donor-conditional — WB runs still
   compress this field because it is rendered in WB output.

5. **Fix MM**: Display/abstraction decisions are entirely the UI developer's
   responsibility. The API change is additive only — no existing response shapes
   are modified.
