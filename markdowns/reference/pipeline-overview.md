---
title: Pipeline Overview
type: reference
status: current
owner: backend
last_verified: 2026-06-09
code_refs:
  - pipeline/orchestrator.py
  - pipeline/manifest.py
  - models.py
  - api/routers/sessions.py
related:
  - reference/orchestration.md
  - reference/artifacts.md
  - reference/data-model.md
  - reference/api.md
---

# Pipeline Overview

`cv-drafter` reformats a candidate's CV into a donor-specific Word document (GIZ or World Bank)
using a chain of seven single-call LLM "agents" with deterministic Python glue around each one.
A human approves the work at three checkpoints.

## Stack

| Layer | Tech |
|-------|------|
| HTTP API | FastAPI (`api/`), JWT auth via Supabase |
| Persistence | Supabase Postgres (the `sessions` row) + Supabase Storage (binary blobs) |
| Orchestration | Phase-based background tasks (`pipeline/orchestrator.py`) |
| LLM | Anthropic — Opus 4.8 for extraction (A1), Sonnet 4.6 for A2–A7 (`pipeline/config.py`) |
| Rendering | `docxtpl` over a per-run dynamic Word template (`templates/`) |

## The seven agents

| # | Agent | Module | Job |
|---|-------|--------|-----|
| A1 | CV Extractor | `cv_extractor.py` | Raw CV text → structured `CVData` |
| A2 | ToR Summarizer | `tor_summarizer.py` | Raw ToR text → `DistilledToR` pool(s) |
| A3 | CV–ToR Mapper | `cv_tor_mapper.py` | Score & select the relevant projects |
| A4 | Fields Generator | `fields_generator.py` | Generate donor-specific content (KQ / detailed tasks) |
| A5 | Content Reviewer | `content_reviewer.py` | Flag issues, apply low-severity fixes |
| A6 | Compressor | `compressor.py` | Shorten to the page budget |
| A7 | Field Editor | `field_editor.py` | Apply post-completion user edits (out of band) |

Each agent is **one prompted LLM call** (no tool loop), reads/writes JSON artifacts under
`runs/{session_id}/`, and updates a manifest step. See `reference/agents/` for each.

## Four phases and three checkpoints

The pipeline runs as four FastAPI background-task phases; it halts at a checkpoint after each of the
first three and waits for the user to approve before scheduling the next.

```
POST /start
  └─ Phase 1  run_phase1   A1 + A2 (parallel)            → checkpoint_1_pending
       approve/checkpoint_1
  └─ Phase 2  run_phase2   A3                            → checkpoint_2_pending
       approve/checkpoint_2
  └─ Phase 3  run_phase3   A4 → A5 → A6                  → checkpoint_3_pending
       approve/checkpoint_3
  └─ Phase 4  run_phase4   renderer → upload output.docx → completed
```

A7 (Field Editor) is **post-completion only**: `POST /field-edit` mutates the generated data and
returns the session to `checkpoint_3_pending` for a re-render. Full control flow, the coarse status
machine, and the manifest are documented in `reference/orchestration.md`.

## End-to-end data flow

```
CV/ToR bytes (Supabase Storage)
   │  pipeline.extractor.extract_text          (reference/extraction.md)
   ▼
tagged plain text  ──A1──▶ cv_data.json
                   ──A2──▶ tor_data.json
                              │
                  cv_data + tor_data ──A3──▶ mapped_cv.json
                              │
                          mapped_cv ──A4─▶─A5─▶─A6──▶ generated_fields.json
                              │
            generated_fields["generated"] ──renderer──▶ output.docx ──▶ Storage
```

One Pydantic type, **`CVData`**, carries the candidate through three lifecycle stages (extract →
map → generate); `DistilledToR` carries the assignment requirements. Both are defined in `models.py`
and described in `reference/data-model.md`. The on-disk JSON contracts are in
`reference/artifacts.md`.

## Donors (formats)

`FORMAT_PROFILES` in `models.py` defines per-donor behaviour. GIZ generates `key_qualifications`
bullets; World Bank generates `detailed_tasks`. Rendering and the fields each donor actually shows
are covered in `reference/renderer.md`.

## Observability

Coarse progress is the `sessions.status` column; fine progress is `runs/{id}/manifest.json` (per-step
status, timing, and accumulated agent warnings). Both are exposed over HTTP and polled by the UI —
see `reference/api.md` and `frontend/progress-and-warnings.md`.
