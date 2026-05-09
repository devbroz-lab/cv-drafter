# Agent Input Template Context (Brief)

Quick reference for how each pipeline agent assembles its LLM user message in practice.

---

## Tag-based input assembly matrix

| Agent | File | Reads from | User message tags / structure |
|---|---|---|---|
| CV Extractor (A1) | `pipeline/agents/cv_extractor.py` | extracted CV text + pipeline params | Uses `<cv>...</cv>` text block (not `<cv_data>` yet; this step creates CVData) |
| ToR Summarizer (A2) | `pipeline/agents/tor_summarizer.py` | extracted ToR text | Uses `<tor>...</tor>` text block (or no-ToR fallback instruction) |
| CV-ToR Mapper (A3) | `pipeline/agents/cv_tor_mapper.py` | `cv_data.json`, `tor_data.json`, `manifest.json` | `<cv_data>...</cv_data>`, `<tor_data>...</tor_data>`, `<params>...</params>`, **`<pre_computed>...</pre_computed>`** (conditional — only if relevance pre-compute stub returns non-None; currently unused) |
| Fields Generator (A4) | `pipeline/agents/fields_generator.py` | `mapped_cv.json`, `tor_data.json`, `manifest.json` | `<cv_data>...</cv_data>` (with pre-computed `duration` and `year` per project), `<tor_data>...</tor_data>`, `<format_profile>...</format_profile>`, `<params>...</params>` |
| Content Reviewer (A5) | `pipeline/agents/content_reviewer.py` | `generated_fields.json`, `tor_data.json`, warnings + computed context | `<cv_data>...</cv_data>`, `<tor_data>...</tor_data>`, `<generation_warnings>...</generation_warnings>`, `<pre_computed>...</pre_computed>` |
| Compressor (A6) | `pipeline/agents/compressor.py` | `generated_fields.json`, `tor_data.json`, compression targets | `<cv_data>...</cv_data>`, `<tor_data>...</tor_data>`, `<compression_params>...</compression_params>` (includes `words_before` and `words_per_field` pre-computed by Python), **`<generation_warnings>...</generation_warnings>`** (passthrough) |
| Field Editor (A7) | `pipeline/agents/field_editor.py` | scalar field value resolved from `generated_fields.json["generated"]` + instruction + context from orchestrator | **Not tag-envelope based.** Prompt has labelled sections: `Field key`, `Donor format`, `Word limit`, `CV context`, `Field path`, `Current value`, `Edit instruction` |

---

## Canonical pattern notes

- The `<cv_data>` / `<tor_data>` envelope pattern starts at A3 and is used by A3–A6.
- A1 and A2 are extraction steps, so they use raw text wrappers (`<cv>`, `<tor>`) instead of structured CVData.
- A7 (`field_editor`) is intentionally per-field and does not use the multi-block tag envelope.

---

## Example snippets (current shape)

- A3 (`cv_tor_mapper.py`) builds:
  - `<cv_data>...`
  - `<tor_data>...`
  - `<params>...`
  - `<pre_computed>...` (conditional — only when relevance pre-compute returns non-None; currently deferred)

- A4 (`fields_generator.py`) builds:
  - `<cv_data>...` (with Python pre-computed `duration` and `year` per project)
  - `<tor_data>...`
  - `<format_profile>...`
  - `<params>...`

- A5 (`content_reviewer.py`) adds review-specific context blocks:
  - `<generation_warnings>...`
  - `<pre_computed>...` (tier, experience years, geographic alternative, etc.)

- A6 (`compressor.py`) adds:
  - `<compression_params>...` (includes Python-computed `words_before` and `words_per_field`)
  - `<generation_warnings>...` (passthrough from A4)

- A7 (`field_editor.py`) uses plain labelled sections (not tag-envelope):
  - `Field key:`, `Donor format:`, `Word limit:`, `CV context:`, `Field path:`, `Current value:`, `Edit instruction:`

This is the current practical contract for agent input assembly.

