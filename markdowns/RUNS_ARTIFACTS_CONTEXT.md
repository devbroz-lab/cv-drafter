# Run-directory JSON artifacts (`runs/{session_id}/`)

Reference for **how JSON files under a session folder relate**, which **domain entity** each file carries, and **what consumes it versus what produces it**. Implementation sources: [`pipeline/manifest.py`](pipeline/manifest.py), [`pipeline/orchestrator.py`](pipeline/orchestrator.py), and agents under [`pipeline/agents/`](pipeline/agents/).

Non-JSON artifacts in the same directory (same session) include unpacked Word working trees (`_*_template_unpacked/`), optional `input/` during Phase 1, and final **`output.docx`**; this document focuses on **JSON only**.

---

## 1. Ordering and dependency graph

Artifacts appear in roughly this pipeline order:

```text
(plain CV / ToR text from extractor — not persisted as JSON)
        │
        ├──────────────────────┬───────────────────┐
        ▼                      ▼                   │
  cv_data.json            tor_data.json            │
(CVExtractor)           (TorSummarizer)            │
        │                      │                   │
        └──────────┬───────────┘                   │
                   ▼                               │
           mapped_cv.json                          │
           (CvTorMapper)                           │
                   │                               │
                   ▼                               │
         generated_fields.json  ◄───────────────────┘
         (FieldsGenerator → initial write)
                    │
                    ├─ ContentReviewer (in-place updates: adds "review" block)
                    ├─ Compressor (in-place updates: adds "compression" block)
                    │
                    └─ [post-completion only]
                       FieldEditor (in-place updates: mutates "generated" only)
                       Triggered by POST /field-edit after pipeline reaches "completed"

manifest.json — created at start of Phase 1, updated every step; read by agents that need `params` or step metadata.
```

---

## 2. File-by-file reference

| File | Domain entity(ies) inside the file | Produced as output by | Consumed as input by |
|------|-----------------------------------|-------------------------|----------------------|
| **`manifest.json`** | **`params`**: runtime pipeline dict (`proposed_position`, `donor`, `target_words`, `compression_ratio`, etc.). **`steps[]`**: operational step statuses (not a CV schema). | [`create_manifest`](pipeline/manifest.py) + [`pipeline/orchestrator`](pipeline/orchestrator.py) Phase 1; [`update_step`](pipeline/manifest.py) throughout. | [`cv_tor_mapper`](pipeline/agents/cv_tor_mapper.py), [`fields_generator`](pipeline/agents/fields_generator.py), [`compressor`](pipeline/agents/compressor.py); [`GET /sessions/{id}/manifest`](api/routers/sessions.py). |
| **`cv_data.json`** | Wrapper: **`data`** → **[`CVData`](models.py)** (extracted consultant profile). Optional audit: **`approved`**, **`approved_at`**. | [`cv_extractor`](pipeline/agents/cv_extractor.py), from tagged CV **plain text** + injected session fields (`proposed_position`, `category`, `employer`, `years_with_firm` from `params`). | [`cv_tor_mapper`](pipeline/agents/cv_tor_mapper.py) (reads `["data"]` as CV input to mapping). |
| **`tor_data.json`** | Wrapper: **`data`** → **[`DistilledToR`](models.py)** (structured ToR/JD summary). Optional audit: **`approved`**, **`approved_at`**. | [`tor_summarizer`](pipeline/agents/tor_summarizer.py), from tagged **ToR plain text**, or **`""`** if no ToR was uploaded. | [`cv_tor_mapper`](pipeline/agents/cv_tor_mapper.py), [`fields_generator`](pipeline/agents/fields_generator.py), [`content_reviewer`](pipeline/agents/content_reviewer.py), [`compressor`](pipeline/agents/compressor.py). |
| **`mapped_cv.json`** | Wrapper adds **`approved`**, **`approved_at`**. Core payload: **`data`** → **[`CVData`](models.py)** (same schema; filtered `relevant_projects`). **`alignment`** → relevance / scoring report (mapper-specific structure). | [`cv_tor_mapper`](pipeline/agents/cv_tor_mapper.py), from `cv_data.json` + `tor_data.json` + `manifest.json` (for params). | [`fields_generator`](pipeline/agents/fields_generator.py) (uses filtered CVData + DistilledToR + format profile derived from donor). |
| **`generated_fields.json`** | Evolving envelope for late pipeline: **`generated`** → **[`CVData`](models.py)** (filled + format-specific bullets such as `generated_fields` list). **`generation_warnings`**: list from the generator (passed through by compressor). **`review`**: reviewer verdict + issues (updated by reviewer — see shape note below). **`compression`**: **[`CompressionResult`](models.py)** Pydantic model (updated by compressor; includes `target_not_reached` flag and `protected_field_restorations` audit). Audit: **`approved`**, **`approved_at`**. | **Initial write:** [`fields_generator`](pipeline/agents/fields_generator.py). **In-place updates (pipeline):** [`content_reviewer`](pipeline/agents/content_reviewer.py), [`compressor`](pipeline/agents/compressor.py). **In-place updates (post-completion):** [`field_editor`](pipeline/agents/field_editor.py) via `POST /field-edit` (mutates `generated` key only, preserves all other keys). Legacy overrides via [`POST /sessions/{id}/resolve`](api/routers/sessions.py) may also edit `generated` before resume. | [`content_reviewer`](pipeline/agents/content_reviewer.py), [`field_editor`](pipeline/agents/field_editor.py), [`compressor`](pipeline/agents/compressor.py); [`templates/giz.py`](templates/giz.py) / [`templates/wb.py`](templates/wb.py) (renderers read **`generated_fields["generated"]`**); [`GET /sessions/{id}/output`](api/routers/sessions.py) and [`GET /sessions/{id}/review`](api/routers/sessions.py). |

### `generated_fields.json` — `review` block shape

```json
{
  "high_severity": [
    {
      "path": "relevant_projects[2].date_from",
      "field": "Date consistency",
      "issue": "date_from 2019 is later than date_to 2017",
      "recommendation": "Correct date_from to 2015",
      "solvability": "pipeline"
    }
  ],
  "low_severity": [
    {
      "path": "generated_fields[0].content",
      "field": "Filler language",
      "issue": "Contains 'responsible for'",
      "original": "Was responsible for managing grid inspections",
      "fixed": "Managed grid inspections across 3 provinces",
      "solvability": "pipeline"
    }
  ],
  "passed": false,
  "demoted": {
    "experience_gap_injections": [...],
    "word_count_removals": [...]
  }
}
```

**`solvability`** is present on every finding (both severities):
- `"pipeline"` — `field_editor` can resolve by rewriting the scalar field value.
- `"human"` — requires recruiter judgement or information outside the pipeline.

**`demoted`** has exactly two keys (`experience_gap_injections`, `word_count_removals`). The four legacy demotion keys (`wb_tor_source_demotions`, `geographic_demotions`, `language_demotions`, `leadership_verb_demotions`) no longer exist.

---

## 3. Same entity, different lifecycle stage

The **[`CVData`](models.py)** entity appears in multiple files; the **meaning** changes by stage:

1. **`cv_data.json`** → **`data`**: faithful extraction from the source CV (plus session-injected proposal/firm fields). `generated_fields` on the model is intentionally empty here.
2. **`mapped_cv.json`** → **`data`**: same schema, **`relevant_projects`** filtered by ToR relevance; **`alignment`** documents what was kept or dropped.
3. **`generated_fields.json`** → **`generated`**: same schema again after derived-field fill, **`generated_fields`** list population (format-specific generation), reviewer fixes, field-editor user-directed edits, then compressor shortening.

So: **one Pydantic type (`CVData`), three artifact roles** — extract → map → generate/review/compress.

The **[`DistilledToR`](models.py)** entity lives only under **`tor_data.json`** → **`data`**, and is **read** by every downstream step that needs assignment requirements until rendering (renderers rely on **`generated`**, not `tor_data.json` directly).

---

## 4. Checkpoints and `approved_*` fields

At human checkpoints [`POST .../approve/{checkpoint}`](api/routers/sessions.py), [`stamp_approved`](pipeline/artifacts.py) sets **`approved: true`** and **`approved_at`** on the artifact JSON touched at that checkpoint (`cv_data` + `tor_data`, then `mapped_cv`, then `generated_fields`). Those flags are **audit metadata**; orchestration uses DB status and **`manifest.json`** step states, not the stamp for control flow.

---

## 5. Quick lookup: “Which file does agent X touch?”

| Agent | Writes | Reads (typical) |
|-------|--------|------------------|
| CV Extractor | `cv_data.json` | — (CV text passed in-memory) |
| ToR Summarizer | `tor_data.json` | — (ToR text passed in-memory) |
| CV–ToR Mapper | `mapped_cv.json` | `cv_data.json`, `tor_data.json`, `manifest.json` |
| Fields Generator | `generated_fields.json` (create/overwrite envelope; pre-computes `duration` and `year` per project before LLM call) | `mapped_cv.json`, `tor_data.json`, `manifest.json` |
| Content Reviewer | `generated_fields.json` (adds `review` block with `solvability` per finding + `demoted` audit) | `generated_fields.json`, `tor_data.json`, `manifest.json` (for params) |
| Field Editor *(post-completion only)* | `generated_fields.json` (updates `generated` key only; all other keys preserved; receives donor + CV context from orchestrator) | `generated_fields.json` |
| Compressor | `generated_fields.json` (adds `compression` block validated as `CompressionResult`; pre-computes `words_before`/`words_per_field`, post-computes authoritative `words_after`, restores protected fields; passes through `generation_warnings`) | `generated_fields.json`, `tor_data.json`, `manifest.json` |

Orchestrator **always** writes/updates **`manifest.json`** alongside phase transitions (`create_manifest`, `update_step`).
