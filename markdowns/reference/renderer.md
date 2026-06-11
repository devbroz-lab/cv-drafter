---
title: Renderer (GIZ & World Bank)
type: reference
status: current
owner: backend
last_verified: 2026-06-09
code_refs:
  - templates/registry.py
  - templates/giz.py
  - templates/wb.py
  - templates/giz_dynamic_template.py
  - templates/wb_dynamic_template.py
  - pipeline/paths.py
related:
  - reference/artifacts.md
  - reference/data-model.md
  - reference/agents/a4-fields-generator.md
---

# Renderer

Phase 4 turns `generated_fields.json["generated"]` into `runs/{session_id}/output.docx`. Deterministic
— no LLM calls.

## Dispatch

`templates/registry.get_renderer(target_format)` maps `giz → templates.giz.run`,
`world_bank → templates.wb.run`; anything else raises `ValueError`. The donor comes from the session
row's `target_format`.

## Two-step render

1. **Dynamic template preprocessing** (`*_dynamic_template.py` → `build_dynamic_template`):
   the static donor `.docx` (`templates/GIZ-Template.docx` / `WB-Template.docx`) contains Jinja loop
   markers (`{%tr for proj in relevant_projects %}`). Word can't express variable-length tables, so
   the preprocessor counts list lengths from the data and **expands each loop into N indexed rows/
   bullets** (`{{ relevant_projects[0].location }}`, `[1]`, …), writing a run-scoped
   `*-Template.dynamic.docx`. `clean_jinja_runs` first repairs Jinja tags split across `w:t` runs.
2. **Jinja render** (`DocxTemplate(dynamic_path).render(context)`): `context` is built by
   `_build_context(cv_data)` and the result saved to `output.docx`.

`counts` keys (drive loop expansion):
- GIZ: `education, languages, countries_of_experience, relevant_projects, key_qualifications, publications`
- WB: `education, languages, employment_record, relevant_projects, publications`

## `_build_context` — donor differences

Source dict is always `generated_fields["generated"]`.

- **GIZ** (`templates/giz.py`): CEFR-mapped language columns; `key_qualifications` taken from
  `generated_fields` entries (`field_key == "key_qualifications"`) in preference to the extracted
  list; derived `nationality_display` / `other_skills_display`; headers/footers escaped via
  `_xml_str` (`&` → `&amp;`).
- **WB** (`templates/wb.py`): raw language levels; `employment_record` rows; `detailed_tasks` from
  `generated_fields` (`field_key == "detailed_tasks"`) aligned by index to `relevant_projects`.

## What each donor actually renders (important)

The GIZ project row renders `project_name`, `positions_held`, dates, location, company, and
**`main_project_features`** — but **not `activities_performed`**. So for GIZ the only descriptive
project text the reader sees is `main_project_features`; A4 writes the full project narrative there
(see `reference/agents/a4-fields-generator.md`). WB renders `main_project_features` and
`activities_performed` separately, plus the generated `detailed_tasks`.

## Output & upload

`run_phase4` reads `output.docx` and uploads it to Supabase Storage at
`{session_id}/output/round_{NN}_{target_format}.docx` (`build_object_path`, `NN` = zero-padded
`sessions.round`), records `output_storage_key`, and sets `completed`.

## Paths (`pipeline/paths.py`)

`runs/{id}/output.docx`, `runs/{id}/GIZ-Template.dynamic.docx` (+ `_giz_template_unpacked/`), WB
equivalents. Cleanup: `build_dynamic_template` removes a prior unpack dir / dynamic file before
writing fresh.

## Failure modes

Missing run dir, missing/invalid `generated_fields.json`, empty `generated`, missing static template,
missing `word/document.xml`, preprocess exceptions, or a docxtpl render mismatch all surface as a
Phase 4 failure (`set_failed`).
