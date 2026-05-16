# Referencing System — Current Pipeline Reality (Backend + Frontend)

This document describes how referencing and field editing work **today** in the live codebase.
It supersedes older descriptions that assume a `field_editor_pending` pause in the main pipeline.

---

## 1) What "referencing" means right now

There are two distinct UX modes in `DocxViewer`:

1. `reference` mode (completed output)
   - Click content in `output.docx`
   - Capture structural locator + comment
   - Export as JSON (`[{ locator, comment }]`) via "Copy all as JSON"

2. `field_editor` mode (targeted edits)
   - Click content and auto-map locator -> CVData `field_path`
   - Add `instruction`
   - Submit `POST /sessions/{id}/field-edit` as:
     - `{ edits: [{ field_path, instruction }] }`

Both modes rely on structural parsing of `word/document.xml` from DOCX bytes in the browser.

---

## 2) Current backend phase flow (authoritative)

Current orchestrator behavior:

- Phase 1: `cv_extractor` + `tor_summarizer` -> `checkpoint_1_pending`
- Phase 2: `cv_tor_mapper` -> `checkpoint_2_pending`
- Phase 3: `fields_generator` -> `content_reviewer` (non-blocking) -> `compressor` -> `checkpoint_3_pending`
- Phase 4: renderer -> upload `output.docx` -> `completed`

Important current fact:
- There is **no active phase halt at `field_editor_pending`** in the backend orchestrator.
- Post-generation edits are now handled after completion via `POST /field-edit`.

---

## 3) Current backend field-edit contract

`POST /sessions/{id}/field-edit` currently:

- Requires session status `completed`
- Accepts 1 to 5 edits
- Increments round (`increment_round`)
- Sets status to `processing`
- Runs field editor synchronously (returns `applied` / `skipped` in response)
- Sets manifest:
  - `checkpoint_3` -> `pending`
  - `renderer` -> `waiting`
- Moves DB status to `checkpoint_3_pending`
- Requires `POST /approve/checkpoint_3` to re-render updated DOCX

So the edit loop is:

`completed` -> `POST /field-edit` -> `checkpoint_3_pending` -> `POST /approve/checkpoint_3` -> `completed` (new round file)

---

## 4) Current frontend behavior

`SessionWorkspacePage.tsx` and `DocxViewer.tsx` still implement an older flow:

- Field editor UI is shown only when status is `field_editor_pending`
- It opens `preview.docx` via `GET /sessions/{id}/files/preview`
- Submits `POST /field-edit` from that view

But backend now expects:

- `POST /field-edit` only when status is `completed`
- Workflow oriented around editing final output and re-render approval cycle

### Current FE/BE drift

This is a real integration mismatch:

- FE trigger condition: `field_editor_pending`
- BE accepted condition: `completed`

Result:
- With current backend, frontend field-edit panel is not reachable in normal successful runs.
- If manually invoked before completion, backend returns conflict.

---

## 5) Locator generation and mapping mechanics

### Structural locator generation (browser)

`DocxViewer` parses `word/document.xml` and emits:

- Paragraph locator:
  - `{ location: "paragraph", paragraph_index, text_content }`
- Table locator:
  - `{ location: "table", table_index, row_index, cell_index, text_content }`

Indices are structural and zero-based in document order.

### Field-path mapping for field editor

`locatorToDotPath.ts` maps locator -> CVData dot path.

- GIZ mapping: mostly aligned with `giz_dynamic_template.py` structure.
- WB mapping: currently mismatched with `wb_dynamic_template.py` cell composition.

Known WB issues:

- Employment table assumed as 4-cell split in frontend, but backend template composes fewer/combined cells.
- Relevant projects cells are more composite in backend than frontend mapping assumes.
- `tasks_assigned` display comes from `generated_fields` (`detailed_tasks`) in WB renderer, not a direct scalar in `relevant_projects[i]`.

This causes path resolution failures and frequent `skipped` edits for WB.

---

## 6) `/comments` endpoint status

`POST /sessions/{id}/comments` remains functional but is explicitly marked deprecated in backend.

- Response includes deprecation headers (`Deprecation`, `Sunset`, `Link`)
- Preferred successor is `POST /sessions/{id}/field-edit`

Frontend still exposes "Request a revision" via `/comments`, which does not reflect the preferred path.

---

## 7) Effective "current truth" summary

1. Backend canonical revision path is now post-completion `POST /field-edit`.
2. Backend no longer uses `field_editor_pending` as the normal edit gate.
3. Frontend still uses the legacy `field_editor_pending` + `preview.docx` flow.
4. Referencing (`reference` mode with locator JSON export) works independently on completed output.
5. Field-path mapping quality is acceptable for many GIZ cells but problematic for WB composite cells.

---

## 8) Key files (current behavior source)

- Backend
  - `cv-drafter/pipeline/orchestrator.py`
  - `cv-drafter/api/routers/sessions.py`
  - `cv-drafter/api/models/requests.py`
  - `cv-drafter/pipeline/agents/field_editor.py`
  - `cv-drafter/templates/giz_dynamic_template.py`
  - `cv-drafter/templates/wb_dynamic_template.py`
  - `cv-drafter/templates/wb.py`

- Frontend
  - `cv-drafter-ui/src/pages/SessionWorkspacePage.tsx`
  - `cv-drafter-ui/src/components/DocxViewer.tsx`
  - `cv-drafter-ui/src/lib/utils/locatorToDotPath.ts`
  - `cv-drafter-ui/src/lib/api.ts`
  - `cv-drafter-ui/src/lib/types.ts`

