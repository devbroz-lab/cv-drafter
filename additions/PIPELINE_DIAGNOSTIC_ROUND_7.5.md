# Pipeline Diagnostic — Round 7.5 Implementation Record

**Date**: May 2026
**Status**: ✓ Complete
**Trigger**: Production validation of Round 7 fixes surfaced systematic A5
behaviour issues and output quality gaps requiring immediate attention before
further rounds.

---

## Fixes delivered

| Fix | File(s) changed | Summary |
|-----|-----------------|---------|
| R7.5-D | `pipeline/agents/cv_tor_mapper.py` | Added `_protect_current_role` helper; wired into `run()` after `_enforce_threshold_and_cap`. Unconditionally restores the most-recent `date_to="Present"` project dropped by cap enforcement. |
| R7.5-G | `pipeline/agents/cv_tor_mapper.py` | Extended `_sort_by_date_desc` with `primary_key` argument; `countries_of_experience` now sorted by `date_to` descending so ongoing assignments float to top. |
| R7.5-H | `pipeline/precompute_utils.py`, `pipeline/agents/cv_tor_mapper.py` | Added `collapse_by_date_range` general-purpose utility; called at mapper write-time to collapse `countries_of_experience` rows sharing identical `(date_from, date_to)` pairs into single alphabetically-concatenated rows. |
| R7.5-C | `pipeline/agents/cv_tor_mapper.py` | Raised `MIN_PROJECTS_TO_KEEP` 5→10, `MAX_PROJECTS_TO_KEEP` 15→30. Extended A3 `SYSTEM_PROMPT` with transferable-competency tolerance for sector keyword scoring. |
| R7.5-I | `templates/giz.py` | Changed dual-nationality separator from `" / "` to `" and "` in `_build_context`. |
| R7.5-A | `pipeline/agents/content_reviewer.py` | Added `## Style-check scope` section to `SYSTEM_PROMPT_A5`; restricted style/passive-voice checks to `generated_fields[*].content` only; updated `### relevant_projects` review scope to factual issues only. |
| R7.5-B | `pipeline/agents/fields_generator.py` | Added `#### Bullet style — noun/stat-led preference` and `#### Candidate-anchoring rule` subsections to `SYSTEM_PROMPT_A4` GIZ `key_qualifications` section. Applies to both GIZ and WB formats. |
| R7.5-E | `pipeline/agents/cv_extractor.py` | Added `#### Degree-only routing rule` to `### Education` in `SYSTEM_PROMPT_A1`; non-degree entries (short courses, seminars, training programmes) explicitly routed to `training[]`. |
| R7.5-F | `pipeline/agents/fields_generator.py` | Added `training[]` alongside `certifications[]` as allowed KQ bullet evidence source in `SYSTEM_PROMPT_A4`. Editorial judgment applies — selective surfacing only. |

---

## Context

Round 7.5 is an unplanned interim round triggered by human-vs-pipeline comparison
of output `.docx` files across 4 valid runs (Runs 1–4; Run 7 discarded due to
ToR mismatch). All runs used the same two ToRs:
- GIZ South Africa National Short-Term Expert Pool ToR (Runs 1, 4 partially)
- GIZ Western Balkans RE Grid Integration ToR (Runs 2, 3, 4)

Candidates: Keith Katyora (Run 1), Thyrsos Hadjicostas (Run 2), Dejan
Stojadinovic (Run 3), Merita Kostari (Run 4).

Human-authored final CVs were compared against pipeline output `.docx` files for
Runs 2, 3, and 4.

---

## Issues identified and closed without fix

### Issue R7.5-D — R7-A not working for Hadjicostas publications — CLOSED

Suspected: publications section not extracted for Hadjicostas (Run 2). Confirmed
after inspecting source CV: paragraph [18] reads verbatim "Other relevant
information (e.g. publications): Several articles published / presented at
international journals and conferences." There are no individual citation entries
anywhere in the document. The pipeline correctly extracted this single-line vague
statement. R7-A is working — this is a sparse source document, not a pipeline
failure.

### Issue R7.5-G — Language proficiency over-upgraded by CEFR mapping — CLOSED

Suspected: Stojadinovic (Run 3) language table shows C2 for all languages including
secondary languages where human editor used C1. Source CV confirmed: language table
uses numeric `1` for all skills with no directional header. R4-B's
`language_scale_direction` detection has nothing to anchor to, defaults to
`1_best`, maps `1 → C2` for all. Known limitation of numeric-only scales without
directional context — not a fixable bug. Human editorial judgment (C2 vs C1 for
near-native secondary languages) cannot be replicated by the pipeline without
additional evidence in the source CV.

### Issue R7.5-B — Session isolation failure — CLOSED

Suspected after Run 4 appeared to produce output identical to Run 3. Confirmed
not a session isolation bug after reading `content_reviewer.py` — run directory
path resolution is session-specific. Identical output explained by genuinely
overlapping candidate profiles (both Stojadinovic and Kostari have Kosovo
regulatory experience) against the same ToR.

---

## Issues identified and fixed in Round 7.5

### Issue R7.5-A — A5 flags passive constructions in source-extracted fields

**Observed**: Runs 1, 2, 3, 4. A5 consistently flags `activities_performed` and
`main_project_features` entries for passive/infinitive verb constructions
("Assisting", "Providing", "Responsible for"). These are direct extractions of the
candidate's own words from the source CV. A5 has no mandate to critique the writing
style of raw source material. These flags inflate the issue count, push runs over
the `high_severity_count_unusual` threshold, and give the recruiter a bloated
review list including items they cannot meaningfully act on.

**R7.5-A** — `SYSTEM_PROMPT_A5` in `pipeline/agents/content_reviewer.py`.
Prompt-only.

**Planned change**: Add explicit scope restriction — style and language quality
checks (passive voice, weak verbs, filler constructions, hedged language) are
permitted only against `generated_fields[*].content`. Source-extracted fields
(`activities_performed`, `main_project_features`, `key_qualifications[]`) are out
of scope for style review. A5 may still flag these fields for factual issues
(unverifiable claims, inflated figures, unsupported statistics) but not for writing
style or verb construction.

---

### Issue R7.5-C — A4 generates verb-led KQ bullets; convention is noun/stat-led

**Observed**: Runs 2, 3, 4. A4 generates verb-led bullets ("Delivered...",
"Drafted...", "Conducted...", "Designed..."). Human editors consistently use
noun-phrase or year-count-led bullets across all formats:
- "25 years of professional experience in..."
- "8 years of experience in Grid codes..."
- "Extensive experience in energy policy..."
- "More than 37 years of professional experience..."

Runs 3 and 4 produced near-identical bullets for different candidates against the
same ToR — A4 is over-indexing on ToR requirements and under-differentiating on
candidate-specific evidence. A bullet that could apply to any regulatory expert
against this ToR is insufficiently grounded.

**R7.5-B** — `SYSTEM_PROMPT_A4` in `pipeline/agents/fields_generator.py`.
Prompt-only. Applies to both GIZ and WB formats.

**Planned change**: Add two rules to the KQ bullet generation instruction:

1. **Style rule (strong preference, not hard prohibition):** KQ bullets should open
   with a quantified noun phrase — a year-count ("X years of experience in..."), a
   measurable metric ("Led X projects across Y countries..."), or a domain noun
   ("Extensive experience in..."). Verb-led openings ("Delivered...",
   "Conducted...") are not preferred convention. Exceptions are acceptable where a
   verb is inherently stronger (e.g. "Appointed as...", "Elected to...").

2. **Candidate-anchoring rule:** Each bullet must be grounded in evidence unique to
   this candidate. At least one candidate-specific detail must appear — an
   organisation name, country, measurable outcome, role title, or named instrument.
   A bullet that could apply to any candidate with similar experience against this
   ToR is insufficient and must be rewritten with specific evidence.

---

### Issue R7.5-E — Project cap too aggressive; current role dropped on geography mismatch

**Observed**: Runs 2, 3, 4. Human versions include 19–21 projects; pipeline keeps
5–9. More critically, the candidate's most recent/current role is being dropped when
its geography does not match the ToR. Kostari's Power Central Asia project
(01/2021–present) was dropped because it is Central Asia, not Western Balkans —
despite being the candidate's active current role. Human editors always include the
current role regardless of geographic fit.

**R7.5-C** — `SYSTEM_PROMPT_A3` in `pipeline/agents/cv_tor_mapper.py`.
Prompt + Python.

**Planned change**: Broaden A3's keyword scoring tolerance — instruct A3 to
recognise transferable competencies and adjacent experience rather than requiring
tight lexical keyword overlap. A project in power sector regulation in Central Asia
is relevant evidence for a Western Balkans regulatory ToR even without geographic
keyword match. Also raise Python thresholds:
- `MIN_PROJECTS_TO_KEEP`: 5 → **10**
- `MAX_PROJECTS_TO_KEEP`: 15 → **30**

Note: a formula tying these thresholds to `page_limit` is planned for a future
round once a larger sample size is available and renderer templates are stable.

**R7.5-D** — `pipeline/agents/cv_tor_mapper.py`. Python-only.

**Planned change**: After `_enforce_threshold_and_cap` and the minimum-guarantee
restore, add a `_protect_current_role` step. This step checks whether any project
with `date_to = "Present"` (case-insensitive) was dropped during threshold/cap
enforcement. If so, restore it unconditionally to the kept list — regardless of
relevance score — before writing `mapped_cv.json`. If multiple "Present" projects
exist, protect the one with the latest `date_from`. This runs before the R7-B
sort so the restored project is correctly ordered.

---

### Issue R7.5-F — Education table includes marginal training/seminar entries

**Observed**: Runs 2, 3. Pipeline includes short courses, international seminars,
training programs, and language university entries in GIZ Table 1 alongside degree
qualifications. Human editors retain only degree-level qualifications in the
education table.

**R7.5-E** — `SYSTEM_PROMPT_A1` in `pipeline/agents/cv_extractor.py`.
Prompt-only.

**Planned change**: Add explicit routing rule — `education[]` is for degree-level
qualifications only: Bachelor, Master, PhD, LLB, Juris Doctor, professional law or
bar diplomas, and equivalent formal multi-year degrees. Short courses, seminars,
workshops, international training programs, and certificate programs under 6 months
duration go to `training[]` instead. Edge cases (e.g. professional designations
without a degree title) go to `certifications[]` per R7-C rules.

**R7.5-F** — `SYSTEM_PROMPT_A4` in `pipeline/agents/fields_generator.py`.
Prompt-only.

**Planned change**: Add `training[]` to the allowed evidence sources for KQ bullet
generation, alongside `certifications[]` (R7-D). A4 may draw from `training[]`
when a training entry is directly relevant to a ToR required competency and worth
surfacing as a KQ bullet. Same `source="experience"` tagging applies. A4 applies
editorial judgment — not every training entry warrants a bullet. This keeps A1 as
a pure extractor and places judgment where it belongs: in A4.

**Design decision**: Alternative 3 chosen over appending training entries to
`key_qualifications[]` at A1 time. A1 appending is mechanical and risks inflating
KQ with weak seminar-citation entries. A4 drawing from `training[]` is selective
and mirrors the existing R7-D pattern for `certifications[]`.

---

### Issue R7.5-H — R7-B bug: `countries_of_experience` sorted by wrong key

**Observed**: Run 4 (Kostari). Kosovo (01/1999–present) should appear first as the
ongoing assignment but appears third because R7-B sorts by `date_from` descending,
placing 1999 last. Ongoing assignments (`date_to = "Present"`) should always float
to the top.

**R7.5-G** — `pipeline/agents/cv_tor_mapper.py`. Python-only. One-line sort key
change.

**Planned change**: Change the sort key for `countries_of_experience` from
`date_from` descending to `date_to` descending. `_parse_date` already returns
`_current_date()` for "Present" values, so ongoing assignments naturally sort
highest. `relevant_projects` sort key remains `date_from` descending — correct for
projects.

---

### Issue R7.5-I — `countries_of_experience` rows with identical date ranges not collapsed

**Observed**: Human-authored CVs collapse multiple countries sharing an identical
date range into a single row (e.g. "Albania, Bosnia and Herzegovina, Croatia, North
Macedonia, Kosovo, Montenegro, Moldova | 2014 – 2018"). Pipeline renders one row
per country entry. This wastes table space and diverges from human editorial
convention.

**R7.5-H** — `pipeline/precompute_utils.py` (new general function) +
`pipeline/agents/cv_tor_mapper.py` (call site). Python-only.

**Planned change**:

Add `collapse_by_date_range(entries, country_field, date_from_field,
date_to_field)` to `precompute_utils.py`:
- Groups entries by exact `(date_from, date_to)` pair — no fuzzy matching.
- For each group, concatenates country values alphabetically, comma-separated.
- Returns the collapsed list. Ordering handled separately by R7.5-G.
- General-purpose and importable by any future consumer (A7, other renderers,
  additional table types as identified).

Applied in `cv_tor_mapper.py` post-processing in this sequence:

```
1. _enforce_threshold_and_cap      → kept projects
2. _protect_current_role           → restore dropped current role (R7.5-D)
3. sort relevant_projects          → newest-first by date_from desc (R7-B)
4. collapse_by_date_range          → collapse countries_of_experience (R7.5-H)
5. sort countries_of_experience    → ongoing-first by date_to desc (R7.5-G)
6. write mapped_cv.json
```

**Single source of truth**: Collapsing at mapper write-time means both the renderer
and A7 always operate on the same already-collapsed, already-sorted data. No
renderer-side collapsing needed. A3 geography scoring is unaffected — it runs
before this step.

**Exact-match only**: Collapsing triggered only on identical `(date_from, date_to)`
pairs. Deterministic and avoids incorrect merging of genuinely different periods.

---

### Issue R7.5-J — GIZ dual nationality uses "/" separator instead of "and"

**Observed**: Run 4 (Kostari). Human version shows "Republic of Montenegro and
Republic of Kosovo". Pipeline renders "Republic of Montenegro / Republic of Kosovo"
using the `" / "` separator in `giz.py` `_build_context`.

**R7.5-I** — `templates/giz.py` `_build_context`. Python-only. One-line change.

**Planned change**:
```python
# Before
nationality_display = f"{nat1} / {nat2}" if (nat1 and nat2) else (nat1 or nat2)
# After
nationality_display = f"{nat1} and {nat2}" if (nat1 and nat2) else (nat1 or nat2)
```

Applies unconditionally for all dual-nationality entries in GIZ format regardless
of nationality name formatting. WB renderer unaffected — it uses
`personal_info.nationality` directly without a `nationality_display` construction.

---

## Files to be changed

| File | Planned change |
|------|---------------|
| `pipeline/agents/content_reviewer.py` | R7.5-A: restrict style checks to generated fields only |
| `pipeline/agents/fields_generator.py` | R7.5-B: noun/stat-led KQ style + candidate-anchoring; R7.5-F: `training[]` as KQ evidence source |
| `pipeline/agents/cv_tor_mapper.py` | R7.5-C: broaden A3 tolerance + raise MIN/MAX; R7.5-D: protect current role; R7.5-G: `countries_of_experience` sort by `date_to`; R7.5-H call site |
| `pipeline/agents/cv_extractor.py` | R7.5-E: degree-only routing for `education[]` |
| `pipeline/precompute_utils.py` | R7.5-H: `collapse_by_date_range` general utility function |
| `templates/giz.py` | R7.5-I: dual nationality " and " separator |

---

## Implementation sequence

1. R7.5-D — Protect current role (highest correctness priority)
2. R7.5-G — `countries_of_experience` sort key bug (unblocks R7.5-H)
3. R7.5-H — `collapse_by_date_range` utility + call site
4. R7.5-C — Broaden A3 tolerance + raise MIN/MAX thresholds
5. R7.5-I — GIZ dual nationality separator (one-line)
6. R7.5-A — A5 style check scope restriction (prompt)
7. R7.5-B — A4 KQ bullet style + candidate-anchoring (prompt)
8. R7.5-E — A1 education routing (prompt)
9. R7.5-F — A4 `training[]` as KQ source (prompt)

---

## Design decisions

1. **R7.5-H placement**: `collapse_by_date_range` applied at mapper write-time
   (Option A over Option B renderer-time). Single source of truth for both renderer
   and A7. A3 geography scoring unaffected — runs before this step.

2. **R7.5-H matching**: Exact `(date_from, date_to)` pair match only. No fuzzy
   window. Deterministic, avoids incorrect merging of genuinely different periods.

3. **R7.5-E/F design**: Alternative 3 chosen — A1 routes non-degree entries to
   `training[]` (pure extraction); A4 draws from `training[]` selectively when
   generating KQ bullets (editorial judgment). Mirrors R7-D pattern for
   `certifications[]`. Rejected: (A) accept the loss; (B) render `training[]` in
   GIZ template; (D) A1 appends credential-bearing entries to `key_qualifications[]`.

4. **R7.5-C/D thresholds**: `MIN=10`, `MAX=30` as interim values. Formula tying to
   `page_limit` deferred until larger sample size available and renderer templates
   stable.

5. **R7.5-B scope**: Strong preference (not hard prohibition) for noun/stat-led KQ
   bullets applies to both GIZ and WB formats unconditionally — general CV best
   practice. Exceptions: "Appointed as...", "Elected to..." remain acceptable.

6. **R7.5-I scope**: GIZ-only. WB renderer unaffected.
