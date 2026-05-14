# Issue CC — No Relevant Projects When CV Uses Employment-Only Format

**Priority**: High — fix ASAP
**Status**: ✓ Implemented (Round 7 follow-up — field mapping corrected post-Round 6)
**Discovered**: Round 6, Run 4 (Jennifer Garvey, GIZ, South Africa ToR)

---

## What was observed

`cv_data.json` had `relevant_projects: []` and `employment_record` with 12 fully
populated entries (employer, positions_held, description, dates). A3 had nothing
to score — no projects were passed to A4. The rendered document had a blank
"Work undertaken that best illustrates capability" section. A4 generated only
4 thin KQ bullets using the 3 raw `key_qualifications` entries as its only signal.

---

## Root cause

A1 routes experience into either `relevant_projects` or `employment_record`
depending on how the source CV is structured. For CVs with a dedicated project
table, entries go into `relevant_projects`. For CVs with only a flat employment
history (no separate project section), A1 populates `employment_record` only and
leaves `relevant_projects` empty.

A3 scores only `relevant_projects`. When that list is empty, A3 passes nothing
to A4 regardless of how rich `employment_record` is. The pipeline proceeds with
zero project content.

---

## Why it matters

A flat employment history CV is common — many professionals (particularly lawyers,
advisors, and long-tenured consultants) list all experience as employment entries
without separating out project work. The pipeline currently produces a blank
projects section for all such candidates, which is a critical output failure.

---

## Two fix options

### Option A — A1 dual-population (preferred) — IMPLEMENTED

When no dedicated project section exists, A1 populates `relevant_projects` from
`employment_record` entries, mapping fields as follows:

| `employment_record` field | → `relevant_projects` field |
|---|---|
| `employer` | `project_name` |
| `employer` | `company` |
| `positions_held` | `positions_held` |
| `description` | `main_project_features` |
| `from_date` / `to_date` | `date_from` / `date_to` |
| `location` / `country` | `location` |

`client`, `donor`, and `activities_performed` are left as `""` in fallback mode.
`description` is routed to `main_project_features` (project overview paragraph)
rather than `activities_performed` (candidate-actions paragraph) so the renderer's
first description paragraph is populated correctly.

A1 only does this when `relevant_projects` would otherwise be empty. It
adds an `extraction_warnings` entry noting the dual-population:
`"No dedicated project section found — relevant_projects populated from
employment_record entries for pipeline compatibility."`

A Python safety net (`_apply_employment_fallback` in `cv_extractor.py`) mirrors
the same mapping in case the LLM does not follow the prompt instruction.

### Option B — Renderer fallback

When `relevant_projects` is empty after A3, the renderer reads
`employment_record` directly and renders it in the projects section. Simpler
but bypasses A3 scoring entirely — all employment entries would appear regardless
of relevance.

**Option A is preferred** — it keeps A3 scoring in the loop, allows relevance
filtering, and produces a correctly populated artifact chain without renderer
special-casing.

---

## Files to change

| File | Change |
|---|---|
| `pipeline/agents/cv_extractor.py` | A1 prompt: `### Employment-only fallback (all formats)` section — maps `description → main_project_features`, `employer → project_name + company`, leaves `client`, `donor`, `activities_performed` as `""`. Python safety net: `_apply_employment_fallback` mirrors mapping. Short-description warning references `main_project_features`. |
| `tests/test_cv_extractor_prompt.py` | Tests: fallback section presence, GIZ never-empty rule, `main_project_features` + `company` mapping terms, `activities_performed` empty guidance. |
| `tests/test_employment_fallback.py` | New file: 20 unit tests for `_apply_employment_fallback` field routing, warning text, and idempotence. |

---

## Edge cases to handle

- CV has both a project section AND an employment section → do not dual-populate;
  trust A1's normal routing.
- CV has `relevant_projects` populated but sparse (e.g. 1–2 entries) → do not
  dual-populate; sparse is still valid.
- Employment entries with very short descriptions (< 5 words) → include but flag
  in `extraction_warnings` as low-detail: `"relevant_projects[N] (from employment
  record): main_project_features is very short — may be insufficiently detailed."`

---

## Interaction with other fixes

- **Fix V** (merged-cell project name extraction) — orthogonal; Fix V handles
  project name gaps within an existing `relevant_projects` list, not its absence.
- **Fix N** (project floor/threshold) — once `relevant_projects` is populated
  from employment entries, A3's floor (`MIN_PROJECTS_TO_KEEP`) applies normally.
  The floor ensures at least 3 entries survive even if most score below threshold.
- **Fix 4** (Python scoring) — employment-sourced projects will be scored by
  keyword overlap and geography match like any other project. The scoring quality
  depends on description richness, which varies by candidate.
