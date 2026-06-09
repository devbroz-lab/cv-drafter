---
title: Data Model — CVData, DistilledToR, FormatProfile
type: reference
status: current
owner: backend
last_verified: 2026-06-09
code_refs:
  - models.py
related:
  - reference/artifacts.md
  - reference/agents/a1-cv-extractor.md
  - reference/renderer.md
---

# Data Model

All pipeline types live in `models.py` (Pydantic v2). Two root models carry the work; the rest are
sub-models or pipeline-output blocks.

## `CVData` — the candidate

The single most important type. The **same** `CVData` instance flows through three lifecycle stages,
its meaning shifting at each (see `reference/artifacts.md`):

1. **Extracted** (`cv_data.json`) — faithful copy of the source CV.
2. **Mapped** (`mapped_cv.json`) — `relevant_projects` filtered to the ToR-relevant set.
3. **Generated** (`generated_fields.json`) — derived fields filled, `generated_fields` populated,
   reviewed, compressed.

Design rules (stated in `models.py`): all strings default to `""`, all lists to `[]` (never `None`);
the schema is a **superset** of every donor's fields, and each renderer picks what it needs.

### Key fields & sub-models

| Field | Type | Notes |
|-------|------|-------|
| `personal_info` | `PersonalInfo` | title, names, DOB, nationality(+second), residence, email, phone |
| `proposed_position` / `category` / `employer` / `years_with_firm` | str | injected from session params, never extracted |
| `present_position` | str | derived if absent (most-recent role) |
| `education[]` | `Education` | institution, dates, degree, major |
| `key_qualifications[]` | str | extracted profile bullets (GIZ source material) |
| `certifications[]` / `membership_professional_bodies` | list / str | dual-routed credentials |
| `other_skills[]` / `training[]` / `publications[]` | str lists | label-driven routing in A1 |
| `countries_of_experience[]` | `CountryExperience` | country + date range |
| `languages[]` | `LanguageProficiency` | `*_raw`, `*_cefr`, `cefr_inferred` |
| `employment_record[]` | `EmploymentRecord` | WB employment history (GIZ leaves `[]`) |
| `relevant_projects[]` | `RelevantProject` | the core experience section |
| `generated_fields[]` | `GeneratedField` | `{field_key, content, source}` — A4 output; renderers prefer this |
| `extraction_warnings[]` | str | A1 quality flags |
| `language_scale_direction` | `"1_best"\|"1_worst"\|None` | numeric language-scale handling |
| `references[]` / `certification_declaration` | `Reference` / str | optional sections |
| `detailed_tasks[]` | `DetailedTask` | legacy/unused in the active render path (WB tasks go through `generated_fields`) |

**`RelevantProject`** carries both date fields (`date_from`/`date_to`) and derived `year`/`duration`,
plus `main_project_features` (project context) and `activities_performed` (candidate actions). Which
of these a donor renders matters — see `reference/renderer.md`.

**`GeneratedField`** `source` ∈ `"tor" | "experience" | "generated"`. Renderers read `generated_fields`
in preference to the extracted equivalents (e.g. generated `key_qualifications` over the extracted list).

## `DistilledToR` — the assignment

Produced by A2, read by A3–A6. Flat fields plus structured enrichments:

| Field | Notes |
|-------|-------|
| `position_title` / `sector` / `geography` | display + scoping |
| `key_tasks[]` / `required_qualifications[]` | the work |
| `required_competencies[]` / `preferred_competencies[]` | flat lists (the structured mirror is not reliably populated) |
| `sector_keywords[]` | legacy keyword list |
| `country_experience_required[]` | **canonical** geographic requirement (A3 scores on this, not `geography`) |
| `scoring_keywords` | `ScoringKeywords{role_implied, scope_implied, explicit}` — feeds A3's Python relevance scorer |
| `language_requirements[]` / `page_limit_stated` | constraints |

`tor_data.json` wraps **one or more** `DistilledToR` "pools" (multi-role ToRs); the UI selects one at
checkpoint 1. See `reference/artifacts.md` and `reference/agents/a2-tor-summarizer.md`.

## `FormatProfile` & `FORMAT_PROFILES`

Per-donor configuration consumed by A4 and the renderers:

| Donor | `generative_field_keys` | `language_scale` | `page_limit_default` |
|-------|-------------------------|------------------|----------------------|
| `giz` | `["key_qualifications"]` | `cefr` | 4 |
| `world_bank` | `["detailed_tasks"]` | `freetext` | 4 |

Both ship `default_target_words=0` / `default_compression_ratio=0.80`; the active compression target is
computed from the page limit (see `reference/agents/a6-compressor.md`).

## Pipeline-output blocks

- **`CompressionResult`** — A6's audit block in `generated_fields.json["compression"]`
  (`applied`, `words_before/after`, `target_not_reached`, `fields_shortened[]`,
  `protected_field_restorations[]`).
- **`review`** block (plain dict in `generated_fields.json`) — A5's `high_severity[]` /
  `low_severity[]` / `passed`, each finding carrying `solvability` ∈ `"pipeline" | "human"`.

## Gotchas

- `CVData.model_rebuild()` is called at the bottom of `models.py` to resolve the forward reference in
  `generated_fields`.
- `detailed_tasks` (the `DetailedTask` list) is **not** the WB render path — WB tasks are
  `GeneratedField`s with `field_key="detailed_tasks"`. Don't confuse the two.
- `generated_fields` is empty after extraction (A1) and after mapping (A3); it is only populated by A4.
