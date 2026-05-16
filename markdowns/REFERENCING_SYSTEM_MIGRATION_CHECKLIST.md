# Referencing/Field-Edit Migration Checklist

This checklist aligns the frontend with the current backend pipeline where
`POST /sessions/{id}/field-edit` is a **post-completion** revision action.

Related context:
- `markdowns/REFERENCING_SYSTEM_CURRENT_PIPELINE.md`
- `markdowns/FIELD_EDITOR_FE_BE_MISMATCH_CONTEXT.md`

---

## Goal

Move from legacy FE behavior:
- edit UI at `field_editor_pending`
- preview-based edit submission

To current backend behavior:
- edit UI at `completed`
- submit targeted edits via `/field-edit`
- return to `checkpoint_3_pending`
- approve checkpoint 3 to re-render

---

## Phase 1 — Fix Blocking FE/BE Status Mismatch (Highest Priority)

### 1. Show field-edit controls at `completed` (not `field_editor_pending`)

- Update gating logic in `cv-drafter-ui/src/pages/SessionWorkspacePage.tsx`.
- Replace status condition for edit-submit panel from `field_editor_pending` to `completed`.
- Keep completed output viewer available (no regression for reference mode).

Acceptance:
- On a completed session, user can create/edit field instructions and submit.
- No UI path depends on `field_editor_pending`.

### 2. Update post-submit UX for new backend contract

Backend now returns `status: checkpoint_3_pending` for successful `/field-edit`.

- Update success toast/message from "pipeline resuming" to "awaiting checkpoint_3 approval".
- After successful `/field-edit`, refresh status + manifest and guide user to approve checkpoint 3.

Acceptance:
- UI transitions to checkpoint-approval state after edits.
- User sees clear next step: approve checkpoint 3.

### 3. Keep `/comments` clearly secondary/deprecated in UI

- Either hide revision-by-comment or visually mark as legacy fallback.
- Prefer targeted field edits as primary call-to-action.

Acceptance:
- Primary revision path is field edits.
- `/comments` is not the default user path.

---

## Phase 2 — Update Field-Edit Source Document Strategy

### 4. Decide whether to keep preview-based editing

Current backend field-edit is post-completion, so preview artifacts are optional.

Recommended:
- Use `output.docx` for editing in completed state.
- Keep preview fetch path only if there is a separate planned pre-completion workflow.

Acceptance:
- Edit target document source matches status gate (`completed` -> output doc).

### 5. Ensure output query gating matches edit workflow

- Verify output data (`GET /output`) is always available for completed edit flow.
- Keep loading/error states coherent if output is temporarily unavailable.

Acceptance:
- Completed sessions reliably show editable context and data summary.

---

## Phase 3 — Correct Locator->DotPath Mapping (Especially WB)

### 6. Fix WB employment mapping to match template composition

`locatorToDotPath.ts` assumptions are currently too granular for WB employment cells.

- Align mapping with actual `templates/wb_dynamic_template.py` cell composition.
- Do not map nonexistent cell splits to scalar paths.

Acceptance:
- Employment-cell clicks produce resolvable field paths or explicit fallback.

### 7. Fix WB relevant-projects mapping for composite cells

- Reflect that WB project cells are composite in template expansion.
- Avoid pretending each visible fragment is a unique scalar if it is not.

Acceptance:
- Fewer false "mapped" paths in WB.
- Higher edit-apply rate; fewer backend `skipped` due to bad paths.

### 8. Handle `tasks_assigned` explicitly

- Do not map WB task cell to `relevant_projects[i].*` blindly.
- If direct scalar path is not valid, emit fallback with manual user confirmation.

Acceptance:
- Task-cell edits no longer fail silently from invalid semantic mapping.

### 9. Improve paragraph fallback semantics

Current heuristic `key_qualifications.{paragraph_index}` is structurally weak.

- Keep fallback labels explicit ("verify path required").
- Encourage manual correction before submit when confidence is fallback.

Acceptance:
- Users can distinguish reliable mappings from guesses.

---

## Phase 4 — Type/API Contract Cleanup

### 10. Sync frontend `FieldEditResponse` type with backend

Backend response includes `round`; frontend type currently omits it.

- Add `round: number` to `cv-drafter-ui/src/lib/types.ts` `FieldEditResponse`.
- Surface updated round in success UX if useful.

Acceptance:
- No hidden response fields; frontend type matches backend response model.

### 11. Audit stale comments/messages

- Remove old "agent not implemented" messaging where no longer accurate.
- Update copy that references legacy status flow.

Acceptance:
- UI text reflects current backend behavior.

---

## Phase 5 — Verification & Regression Tests

### 12. Manual E2E checks (GIZ)

1. Complete a session to `completed`.
2. Open document viewer and add 1-2 targeted edits.
3. Submit `/field-edit`.
4. Confirm status -> `checkpoint_3_pending`.
5. Approve checkpoint 3.
6. Confirm new `round_XX` output generated and downloadable.

Expected:
- `applied` contains edited paths.
- Re-rendered doc contains intended changes.

### 13. Manual E2E checks (WB)

Repeat the same flow with WB template and include:
- employment cell edit
- project cell edit
- task-like cell interaction

Expected:
- No invalid "mapped" claims for semantically composite cells.
- Fallback paths are clearly flagged for verification.

### 14. Telemetry/log checks

- Track ratio of `applied` vs `skipped` from `/field-edit` responses per format.
- Use this as a quality signal after mapping changes.

Expected:
- WB `skipped` rate decreases after mapping corrections.

---

## Recommended Implementation Order

1. Status-gate/UI-flow fixes (Phase 1)
2. Type and copy cleanup (Phase 4)
3. WB mapping corrections (Phase 3)
4. Document-source simplification (Phase 2)
5. Verification pass (Phase 5)

This order restores functional alignment quickly, then improves edit accuracy.

