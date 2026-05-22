# Fix Label Rename Reference

**Rename applied**: May 2026 — labels below were applied across diagnostic docs,
context markdowns, and Python/test comments via `scripts/rename_fix_labels.py`.
First parenthetical old name kept once per key doc where noted (e.g. `R7.5-B (Fix OO)` in
`PIPELINE_DIAGNOSTIC_ROUND_8.md`).

**Date**: May 2026
**Reason**: Fix labels introduced in Rounds 4–7.5 used an inconsistent
double-letter scheme (Fix N, Fix AA, Fix OO etc.) that grew confusing over time.
From Round 8 onwards, all fixes follow the `R{round}-{letter}` scheme, which
encodes the round of first appearance directly in the label.

Fixes introduced before Round 4 (Fixes 1–9, J, M, S) retain their original
labels — they predate the diagnostic round process and are clearly distinguishable
from the new format. Round 1–3 implementation records (`PIPELINE_DIAGNOSTIC_ROUND_1.md`
through `_ROUND_3.md`) and pre–Round 4 issue/fix references in the master context
doc (Issues A–M, Section 3 Rounds 1–3, Section 4 Rounds 1–3 rows) keep legacy labels
only; do not substitute `R4-A`/`R5-B` etc. there.

---

## Mapping Table

| Previous Label | New Label | Round | Description |
|----------------|-----------|-------|-------------|
| Fix N | R4-A | Round 4 | Raise project floor, lower thresholds, raise cap |
| Fix O | R4-B | Round 4 | Numeric CEFR scale direction detection |
| Fix P | R4-C | Round 4 | A4 prompt: prefer candidate's own KQ bullets |
| Fix Q | R4-D | Round 4 | A1 prompt: route `other_skills` correctly |
| Fix R | R4-E | Round 4 | Optional `references` and `certification_declaration` |
| Fix 4b | R5-A | Round 5 | A2 keyword extraction for Python relevance scoring |
| Fix 4 | R5-B | Round 5 | Python relevance scoring for Agent 3 |
| Fix 2 | R5-C | Round 5 | Upgrade all agents to Sonnet |
| Fix 5b | R5-D | Round 5 | Soft-flag quality warnings in manifest |
| Fix U | R5-E | Round 5 | A1 unfilled placeholder detection |
| Fix V | R6-A | Round 6 | A1 project name extraction from merged-cell layout |
| Fix W | R6-B | Round 6 | A1 date inversion auto-correct across all date fields |
| Fix X | R6-C | Round 6 | Renderer empty `other_relevant_info` — closed as false positive |
| Fix Y | R6-D | Round 6 | A2 `scoring_keywords` prompt fix + soft-flag validator |
| Fix Z | R6-E | Round 6 | Compressor word cap on A6 input |
| Fix AA | R6-F | Round 6 | A4 minimum output guarantee extended to all `generative_field_keys` |
| Fix AB | R6-G | Round 6 | A1 employment-only fallback routing |
| Fix DD | R7-A | Round 7 | A1 prompt: citations in "References" section → `publications[]` |
| Fix EE | R7-B | Round 7 | Post-cap chronological sort of projects and countries at mapper write-time |
| Fix FF-A | R7-C | Round 7 | A1 prompt: formal credentials → `certifications[]` and `membership_professional_bodies` |
| Fix FF-B | R7-D | Round 7 | A4 prompt: draw from `certifications[]` as KQ bullet source |
| Fix GG | R7-E | Round 7 | GIZ renderer: remove education date duplication |
| Fix HH | R7-F | Round 7 | GIZ renderer: ampersand `&` escaping across all text fields |
| Fix R7-5 | R7-G | Round 7 | GIZ renderer: education rows newest-first sort |
| Fix II-A | R7-H | Round 7 | WB renderer: document positional `detailed_tasks` ↔ `relevant_projects` pairing |
| Fix II-B | R7-I | Round 7 | A7: add `RENDERER_FIELD_MAP` per donor |
| Fix JJ | R7-J | Round 7 | Remove A4 truncation-and-restore logic |
| Fix KK | R7-K | Round 7 | Remove A6 truncation (silent data loss) |
| Fix LL | R7-L | Round 7 | A6 donor-aware compression: exclude `activities_performed` for GIZ |
| Fix MM | R7-M | Round 7 | Transmit all pipeline warnings to frontend via API |
| Fix NN | R7.5-A | Round 7.5 | A5 prompt: restrict style checks to generated fields only |
| Fix OO | R7.5-B | Round 7.5 | A4 prompt: noun/stat-led KQ bullet style + candidate-anchoring |
| Fix PP-A | R7.5-C | Round 7.5 | A3 prompt: broaden scoring tolerance; raise MIN=10, MAX=30 |
| Fix PP-B | R7.5-D | Round 7.5 | Protect current role unconditionally after cap enforcement |
| Fix QQ-A | R7.5-E | Round 7.5 | A1 prompt: degree-only routing for `education[]` |
| Fix QQ-B | R7.5-F | Round 7.5 | A4 prompt: draw from `training[]` as KQ evidence source |
| Fix RR | R7.5-G | Round 7.5 | Fix EE bug: `countries_of_experience` sort by `date_to` descending |
| Fix SS | R7.5-H | Round 7.5 | `collapse_by_date_range` general utility + call site in mapper |
| Fix TT | R7.5-I | Round 7.5 | GIZ renderer: dual nationality separator `" / "` → `" and "` |

---

## Labels unchanged (pre-diagnostic legacy)

The following labels predate the diagnostic round process and are retained as-is:

| Label | Description |
|-------|-------------|
| Fix 1 | Upgrade Agent 4 to Sonnet |
| Fix 3 | Centralise CEFR mapping at Agent 1 write time |
| Fix 5a | Hard-block validator after Agent 4 |
| Fix 6 | Surface Agent 7 routing decision via API |
| Fix 7 | `map_cefr` normalisation (parenthetical + numeric sentinel) |
| Fix 8 (Parts 1/2/3) | Project cap, A4 minimum output guarantee, per-project text cap |
| Fix 9 | `FieldShortened.subfield` optional |
| Fix J | Python threshold enforcement for Agent 3 |
| Fix M (Parts 1/2) | Numeric 1–5 CEFR scale mapping; Fix 8 Part 3 restoration |
| Fix S | Compressor word target scaled to `page_limit` (deferred) |

---

## Round 8 onwards — new scheme in use

| Label | Round | Description |
|-------|-------|-------------|
| R8-A | Round 8 | A5 prompt: align style expectations with R7.5-B convention |
| R8-B | Round 8 | A1 prompt: sharpen education routing for partial credits |
| R8-C | Round 8 | Smart 300-word cap for A3 input; cap + restoration for A4 |
| R8-D | Round 8 | CV complexity pre-screen and recruiter warning |
