# Field Editor Frontend/Backend Mismatch Context

## Scope

- This document captures the current implementation analysis for the fields editor flow.
- `cv-drafter/additions` is intentionally out of scope.
- Focus: pipeline behavior and frontend/backend API contract alignment, especially around the field editor agent.

---

## End-to-End Pipeline (Current Behavior)

1. Frontend polls session status and manifest.
2. Backend Phase 3 (`run_phase3`) runs:
   - `fields_generator`
   - `content_reviewer`
   - preview renderer (`preview.docx`, local artifact)
   - marks manifest step `field_editor` as `pending`
   - sets DB status to `field_editor_pending`
3. Frontend opens preview viewer and lets user click document content.
4. Frontend maps clicked locator to a CVData dot path and builds:
   - `[{ field_path, instruction }]` (max 5)
5. Frontend calls `POST /sessions/{id}/field-edit`.
6. Backend validates status must be `field_editor_pending`, then:
   - runs `pipeline.agents.field_editor.run(run_dir, edits)` synchronously
   - returns `applied` and `skipped`
   - sets status to `processing`
   - schedules `run_phase3_after_field_editor` (compressor -> `checkpoint_3_pending`)

Key contract point:
- Backend field editor applies edits against `generated_fields.json["generated"]`.
- Therefore, every frontend `field_path` must resolve inside the CVData object.

---

## API Contract Status

The API payload shape itself is aligned:

- Frontend sends:
  - `{ edits: [{ field_path: string, instruction: string }] }`
- Backend expects exactly that shape with validation:
  - 1 to 5 edits
  - non-empty `field_path`
  - non-empty `instruction`

Path syntax compatibility:
- Backend supports bracket and dot indexing via normalization:
  - `key_qualifications[2]` and `key_qualifications.2` both work.

Conclusion:
- The mismatch is not the HTTP schema.
- The mismatch is the semantic mapping from clicked preview location to `field_path`.

---

## Primary Mismatch: Frontend Locator Mapping vs Backend WB Template Structure

The frontend mapping utility (`cv-drafter-ui/src/lib/utils/locatorToDotPath.ts`) assumes WB table cell layouts that do not match how the backend WB dynamic template composes cells (`cv-drafter/templates/wb_dynamic_template.py`).

### A) WB Employment table cell assumptions differ

Frontend assumption (WB table index 2):
- cell 0 -> `employment_record[i].from_date`
- cell 1 -> `employment_record[i].employer`
- cell 2 -> `employment_record[i].positions_held`
- cell 3 -> `employment_record[i].country`

Backend WB dynamic template reality:
- table index 2 has 3 cells:
  - cell 0 combines period
  - cell 1 combines employer + position
  - cell 2 country

Impact:
- Frontend emits paths for nonexistent structural splits.
- Many edits become unresolved/skipped.

### B) WB Relevant Projects table assumptions differ

Frontend assumption (WB table index 3):
- one field per cell across six cells (`project_name`, `date_from`, `location`, etc.).

Backend WB dynamic template reality:
- table index 3:
  - cell 0 = `tasks_assigned`
  - cell 1 = combined block containing many fields (`project_name`, `year`, `location`, `client`, `main_project_features`, `positions_held`, `activities_performed`)

Impact:
- A click in a combined cell is forced to a single field path by frontend heuristics.
- User intent often does not match the emitted `field_path`.

### C) `tasks_assigned` mapping is not directly editable via relevant project scalar path

In WB renderer context (`cv-drafter/templates/wb.py`):
- `tasks_assigned` is derived from `generated_fields` entries where `field_key == "detailed_tasks"`.
- It is not stored as a simple scalar at `generated.relevant_projects[i].tasks_assigned`.

Impact:
- Clicking WB tasks-assigned cell and mapping to a project scalar path is semantically incorrect.

---

## Secondary Friction (GIZ)

GIZ mapping is mostly closer to backend intent, but still has edge cases:
- Some visible cells render combined values (for example date ranges and grouped content).
- Frontend may map a click to only one underlying path.
- Edits can apply but may feel "partial" from user perspective.

---

## Why Backend Returns `skipped` Frequently in Problem Cases

`pipeline/agents/field_editor.py` skips when:
- path resolution fails (`KeyError`, `IndexError`, `TypeError`)
- resolved value is non-scalar (`list` or `dict`)
- model chooses skip
- write-back fails

Given current FE mapping mismatches, the dominant failure mode is invalid or semantically wrong path resolution.

---

## Practical Summary

1. Frontend and backend agree on endpoint and payload structure.
2. The operational mismatch is in frontend locator-to-path mapping logic (especially WB).
3. WB template cells are more composite than frontend assumes.
4. As a result, frontend-generated paths do not consistently correspond to editable CVData scalar fields used by the backend field editor agent.

---

## Files Inspected (Core)

- Frontend:
  - `cv-drafter-ui/src/components/DocxViewer.tsx`
  - `cv-drafter-ui/src/lib/utils/locatorToDotPath.ts`
  - `cv-drafter-ui/src/lib/api.ts`
  - `cv-drafter-ui/src/pages/SessionWorkspacePage.tsx`
- Backend API and models:
  - `cv-drafter/api/routers/sessions.py`
  - `cv-drafter/api/models/requests.py`
- Backend orchestrator and agent:
  - `cv-drafter/pipeline/orchestrator.py`
  - `cv-drafter/pipeline/agents/field_editor.py`
- Template behavior:
  - `cv-drafter/templates/wb_dynamic_template.py`
  - `cv-drafter/templates/wb.py`
  - `cv-drafter/templates/giz_dynamic_template.py`

