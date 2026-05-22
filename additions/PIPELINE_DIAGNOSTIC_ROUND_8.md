# Pipeline Diagnostic — Round 8 Implementation Record

**Date**: May 2026
**Status**: ⏳ In Progress
**Tests after round**: —

---

## Context

Round 8 addresses issues surfaced during Round 7.5 post-implementation production
validation (5 runs: Runs 1, 2, 3, 5, 6). Primary drivers are:

1. A5 style miscalibration conflicting with R7.5-B (Fix OO) — confirmed across
   Runs 1 and 3.
2. R7.5-E (QQ-A) edge case — partial credit certificates not correctly routed
   to `training[]`.
3. Significant runtime scaling with CV complexity — WB format A1 at 426 seconds
   for 13 projects; 43-project GIZ CV at 218 seconds.
4. First `target_not_reached` compressor warning observed (Run 6, WB format,
   3,770 → 2,108 words).

**Nomenclature note**: From Round 8 onwards, fix labels follow the `R{round}-{letter}`
scheme agreed during Round 7.5 post-run review. Previously implemented fixes
were renamed to `R{round}-{letter}` labels in May 2026 (see `FIX_LABEL_RENAME_MAPPING.md`).

---

## Fixes delivered

_To be completed after implementation._

---

## Production validation — Round 7.5 post-implementation runs

### Run summary

| Run | Candidate | Donor | Projects | A1 runtime | A3 runtime | Reviewer |
|-----|-----------|-------|----------|-----------|-----------|---------|
| Run 1 | Keith Katyora | GIZ | 5 | ~41s | ~88s | blocked |
| Run 2 | Thyrsos Hadjicostas | GIZ | 30 | ~100s | ~106s | blocked |
| Run 3 | Dejan Stojadinovic | GIZ | 43 | ~218s | ~177s | blocked |
| Run 5 | Jennifer Garvey | GIZ | 12 | ~47s | ~96s | blocked |
| Run 6 | Rafael Jabba Jr. | WB | 13 | ~426s | ~250s | passed |

### Fixes confirmed working

- **R7.5-B** — KQ bullet style correct across all runs. Noun/stat-led
  openings throughout. Candidate-specific details present. No verb-led bullets.
- **R7.5-C** — Broader project selection confirmed. Run 2: 10/30 kept
  vs 5/30 in Round 7. Run 3: 12/43 kept vs 9/43. Minimum guarantee at MIN=10
  working correctly.
- **R7.5-D** — Current role protection confirmed. Run 5: Independent
  Consultant (March 2019–Present) correctly retained despite all scores below
  0.10.
- **R7.5-E** — Education routing confirmed. Run 3 (Stojadinovic): 1
  degree entry only, 3 training entries correctly in `training[]`. Run 6: 2 degree
  entries only.
- **R7.5-F** — `training[]` used as KQ source where relevant. Working
  correctly.
- **R7.5-G** — `countries_of_experience` sort by `date_to` descending
  confirmed in mapped_cv artifacts.
- **R7.5-H** — `collapse_by_date_range` working. No identical date-range
  rows observed in test runs (no collapse triggered, but function present).
- **R7.5-I** — Dual nationality "and" separator. No dual-nationality
  candidates in this run set; fix not exercised.
- **R7.5-A** — A5 style check scope restriction working. No passive
  construction flags on source-extracted fields across any run.

### Fix S calibration data points (Round 8 batch)

| Run | Donor | Page limit | Words before compression | Words after | Target | Fired? |
|-----|-------|-----------|--------------------------|-------------|--------|--------|
| Run 1 | GIZ | 5 | 955 | 955 | 2,250 | No |
| Run 2 | GIZ | 4 | 567 | 567 | 1,800 | No |
| Run 3 | GIZ | 4 | 821 | 821 | 1,800 | No |
| Run 5 | GIZ | 4 | 479 | 479 | 1,800 | No |
| Run 6 | WB | 4 | 3,770 | 2,108 | 1,800 | Yes (target not reached) |

**Observation**: GIZ runs continue to come in well under target. WB 4-page run
exceeded target even after compression (2,108 vs 1,800). The 450 words/page
constant is too low for WB format — WB CVs include employment records and detailed
tasks in addition to project descriptions, making them structurally denser than
GIZ at the same page limit. Separate `words_per_page` constants for GIZ and WB
are needed as part of Fix S.

---

## Issues identified in Round 8 production validation

### Issue R8-1 — A5 style miscalibration on generated KQ bullets

**Observed**: Runs 1 and 3. A5 flags noun/stat-led openings on generated KQ
bullets as missing action verbs or passive constructions — directly conflicting
with R7.5-B  which mandates noun/stat-led style. Examples:

- Run 1: *"Bullet begins with '5+ years management and leadership experience
  as...' — missing an action verb at the start"*
- Run 3: *"Begins with 'Demonstrated capacity building experience' — passive
  construction leading with an adjective rather than an active verb"*

R7.5-A correctly stopped A5 from flagging source-extracted fields for
style issues. But A5's internal style expectations for generated content were not
updated to match R7.5-B's convention — A5 still expects verb-led openings on KQ
bullets and flags noun/stat-led openings as deficient.

**R8-A** — `SYSTEM_PROMPT_A5` in `pipeline/agents/content_reviewer.py`.
Prompt-only.

**Planned change**: Add explicit style alignment instruction — noun-phrase, stat-led
("X years of experience in..."), or domain-noun openings ("Extensive experience
in...") on KQ bullets are the preferred convention and must not be flagged as
missing action verbs or passive constructions. Only flag KQ bullet style where
the opening is genuinely ambiguous or misleading — not where it follows the
noun/stat-led convention.

---

### Issue R8-2 — R7.5-E edge case: partial credit certificate in `education[]`

**Observed**: Run 5 (Jennifer Garvey). `education[]` contains "Credit Certificate
towards Juris Doctor degree granted by University of Wisconsin" — a partial credit
certificate, not a degree-level qualification. R7.5-E (QQ-A) correctly routes
seminars and short courses to `training[]` but the A1 routing rule does not
explicitly address partial credits and certificate programmes that are named
similarly to degrees.

**R8-B** — `SYSTEM_PROMPT_A1` in `pipeline/agents/cv_extractor.py`.
Prompt-only.

**Planned change**: Sharpen the `education[]` routing rule — add explicit exclusion
for: partial credit certificates, credit-towards-degree programmes, non-completing
enrolments, and certificate programmes without a named degree qualification. These
go to `training[]`. A qualification must have a completed, named degree title
(Bachelor, Master, PhD, LLB, Juris Doctor, MBA, etc.) to be placed in
`education[]`.

---

### Issue R8-3 — Runtime scaling with CV complexity

**Observed**: All runs. Agent runtimes scale significantly with project count and
format complexity:

| Agent | 5 proj GIZ | 30 proj GIZ | 43 proj GIZ | 13 proj WB |
|-------|-----------|-------------|-------------|-----------|
| A1 | ~41s | ~100s | ~218s | ~426s |
| A3 | ~88s | ~106s | ~177s | ~250s |
| A4 | ~100s | ~77s | ~118s | ~219s |
| A5 | ~101s | ~84s | ~136s | ~217s |

WB format A1 at 426s for 13 projects is disproportionate — the WB schema
requires extraction of `employment_record`, `detailed_tasks`, and
`world_bank_affiliation` in addition to the standard GIZ fields, making the
output JSON significantly larger.

Two fixes identified:

**R8-C** — Smart input cap at 300 words for A3 and A4 inputs.
`pipeline/agents/cv_tor_mapper.py` + `pipeline/agents/fields_generator.py`.
Python-only.

**Planned change**:
- For A3: cap `activities_performed` + `main_project_features` per project at 300
  words in the scoring prompt. A3 only needs enough text to score relevance — it
  does not need verbatim paragraphs. No restoration needed (A3 does not write
  project text to output).
- For A4: cap at 300 words per project field for the generation prompt. Restore
  originals from pre-cap copy before writing to `generated_fields.json` — same
  restoration pattern as the original R7-J (which was removed in R7-J because
  the cap was too small at 150 words; 300 words is sufficient for quality
  grounding).

**R8-D** — CV complexity pre-screen.
`pipeline/orchestrator.py` / API layer. Python-only.

**Planned change**: Before triggering A1, estimate CV complexity from document
metadata (page count, word count, or file size). If complexity exceeds a threshold
(e.g. >15 pages or >8,000 words estimated), surface a warning to the recruiter
via the API: processing may take 5–10 minutes. No pipeline change — pure
expectation management.

---

### Issue R8-4 — Compressor `target_not_reached` on WB 4-page runs

**Observed**: Run 6. Compressor reduced 3,770 → 2,108 words against a 1,800-word
target — 308 words over target. The `target_not_reached` manifest warning fired
correctly. WB format is structurally denser than GIZ at the same page limit due
to employment records and detailed tasks. The 450 words/page constant is
insufficient for WB runs.

**Resolution**: This is a Fix S calibration issue. The WB format requires a higher
`words_per_page` constant than GIZ. Separate constants for each donor format
should be introduced as part of Fix S implementation. Deferred to Round 9 as
per Fix S scope. Recorded here as a calibration data point.

---

## Files to be changed

| File | Planned change |
|------|---------------|
| `pipeline/agents/content_reviewer.py` | R8-A: align A5 style expectations with R7.5-B convention |
| `pipeline/agents/cv_extractor.py` | R8-B: sharpen education routing for partial credits |
| `pipeline/agents/cv_tor_mapper.py` | R8-C: 300-word cap for A3 input |
| `pipeline/agents/fields_generator.py` | R8-C: 300-word cap + restoration for A4 input |
| `pipeline/orchestrator.py` / API | R8-D: complexity pre-screen and recruiter warning |

---

## Implementation sequence

1. R8-A — A5 style alignment (prompt-only, immediate)
2. R8-B — A1 partial credit routing (prompt-only, immediate)
3. R8-C — Smart 300-word cap for A3 and A4
4. R8-D — Complexity pre-screen

---

## Deferred to Round 9

| Label | Description | Reason |
|-------|-------------|--------|
| Fix S | Compressor word target scaled to `page_limit`; separate GIZ/WB constants | Pending ≥5 calibration runs per template per page limit |
| R5-B threshold recalibration | Review 0.30/0.40/0.50 score tier constants | Pending stable score distribution after R7.5-C |
| ToR caching | Cache `tor_data.json` by ToR file hash to skip A2 on repeated ToRs | Infrastructure dependency — shared ToR store needed |

---

## Design decisions

1. **R8-C cap value**: 300 words chosen (vs 150 in the removed R7-J/KK) as a
   balance between runtime reduction and grounding quality. At 300 words per field,
   A4 sees enough project text to identify candidate-specific details for KQ
   bullets. A3 at 300 words has sufficient context for relevance scoring without
   verbatim paragraphs.

2. **R8-C restoration for A4, not A3**: A3 scores projects but does not write
   project text to output — no restoration needed. A4 generates KQ bullets from
   project text and the output contains the full project data — restoration from
   pre-cap copy is required before writing `generated_fields.json`.

3. **R8-D scope**: Pure expectation management — no pipeline change. Threshold
   TBD from further runtime data but suggested at >15 pages or >8,000 document
   words as initial values.

4. **Fix S WB constant**: Run 6 confirms WB 4-page target of 1,800 words is too
   low — actual post-compression output was 2,108 words. A separate
   `WB_WORDS_PER_PAGE` constant (suggested ~600–650) is needed alongside the
   existing GIZ constant (~450). To be calibrated in Round 9 with additional WB
   runs.

5. **Nomenclature**: Round 8 fixes use `R8-A`, `R8-B`, `R8-C`, `R8-D`. Round 4–7.5
   fixes use `R{round}-{letter}` labels applied May 2026. See
   `FIX_LABEL_RENAME_MAPPING.md` for the historical rename table.

---

## Fix label rename mapping table (Round 4 onwards)

Applied May 2026 across context files, code comments, and tests. Authoritative
mapping (previous label → new label): see `FIX_LABEL_RENAME_MAPPING.md`.

| New label | Round |
|----------|-------|
| R4-A through R4-E | Round 4 |
| R5-A through R5-E | Round 5 |
| R6-A through R6-G | Round 6 |
| R7-A through R7-M | Round 7 |
| R7.5-A through R7.5-I | Round 7.5 |
| R8-A through R8-D | Round 8 |
