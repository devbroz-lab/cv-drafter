# Field Editor UI — Integration Context

Reference for aligning the frontend field editor flow with the current backend
contract. Covers trigger condition fix, locator-to-dot-path mapping correction
for both GIZ and WB formats, composite cell dropdown behaviour, and the
`tasks_assigned` special case.

---

## 1. Current State vs. Target State

| Concern | Current (broken) | Target (correct) |
|---------|-----------------|-----------------|
| FE trigger condition | `field_editor_pending` | `completed` |
| Document opened in viewer | `preview.docx` via `GET /files/preview` | `output.docx` via `GET /files/output/download-url` |
| WB employment cell layout | 4-cell split assumed | 3-cell layout (see §4) |
| WB relevant projects cell layout | 6-cell split assumed | 2-cell layout (see §4) |
| `tasks_assigned` path | `relevant_projects[i].tasks_assigned` (scalar, wrong) | `generated_fields[j].content` where `field_key == "detailed_tasks"` aligns to project row (see §5) |
| Composite cell UX | No handling | Tooltip dropdown on click; inline instruction input; batch-compatible (see §6) |
| `/comments` exposure | "Request a revision" button visible | Removed; field edit panel is sole revision mechanism |

---

## 2. Trigger Condition Fix (`SessionWorkspacePage.tsx`)

The field editor panel must activate when `session.status === "completed"`, not
`"field_editor_pending"`. The backend no longer enters `field_editor_pending`
during normal pipeline runs.

**Status conditions and what the UI should show:**

```
queued / processing / checkpoint_*_pending  →  pipeline progress view
reviewer_blocked                            →  reviewer issue panel + resolve UI
completed                                  →  output DocxViewer + field edit panel
                                              (field edit is optional; user can
                                               just download without editing)
checkpoint_3_pending (post field-edit)     →  approval UI before re-render
failed                                     →  error state
```

**Document to load:**
When `status === "completed"`, fetch the signed URL via
`GET /sessions/{id}/files/output/download-url` and pass it to DocxViewer.
Remove any reference to `GET /sessions/{id}/files/preview` — that route
no longer exists in the current backend.

---

## 3. Post-Edit Flow (State Machine in the UI)

After the user submits a field-edit batch:

```
completed
  ↓ POST /field-edit  (returns { status: "processing", round, applied, skipped })
processing             ← poll GET /status every 2–3s
  ↓
checkpoint_3_pending   ← show applied/skipped summary + approval UI
  ↓ POST /approve/checkpoint_3
processing             ← poll GET /status (renderer running)
  ↓
completed              ← reload DocxViewer with fresh signed URL for new round
```

Key points:
- `POST /field-edit` responds immediately with `status: "processing"` — the
  field editor agent runs as a background task. Poll `GET /sessions/{id}/status`
  until `checkpoint_3_pending`.
- Display `applied` and `skipped` from the `POST /field-edit` response to the
  user before they see the approval button. Skipped paths must be shown clearly —
  see §7.
- After the second `completed`, fetch a fresh signed URL and reload the
  DocxViewer. The old signed URL points to the previous round's file.

---

## 4. Locator-to-Dot-Path Mapping (`locatorToDotPath.ts`)

All table indices are zero-based in document order. Row indices are zero-based
within the table; header rows are row 0, so data rows start at row 1
(`array_index = row_index - 1`). Cell indices are zero-based within the row.

### 4.1 WB Table Layout (ground truth from `wb_dynamic_template.py`)

The WB template has 4 tables (indices 0–3):

#### Table 0 — Education (3 cells per data row)

| cell_index | CVData field | Composite? |
|------------|-------------|------------|
| 0 | `education[i].institution` | No |
| 1 | `education[i].degree` | No |
| 2 | `education[i].date_obtained` | No |

#### Table 1 — Languages (4 cells per data row)

| cell_index | CVData field | Composite? |
|------------|-------------|------------|
| 0 | `languages[i].language` | No |
| 1 | `languages[i].reading_raw` | No |
| 2 | `languages[i].speaking_raw` | No |
| 3 | `languages[i].writing_raw` | No |

#### Table 2 — Employment Record (3 cells per data row)

The frontend previously assumed 4 cells. The backend renders 3. Cell 1 contains
both `employer` and `position` as two paragraphs in one cell — there is no
separate cell for `position`.

| cell_index | CVData field(s) | Composite? |
|------------|----------------|------------|
| 0 | `employment_record[i].period` | No |
| 1 | `employment_record[i].employer`, `employment_record[i].position` | **Yes — 2 fields** |
| 2 | `employment_record[i].country` | No |

Cell 1 triggers the composite dropdown with two options:
- `Employer`  → `employment_record[i].employer`
- `Position`  → `employment_record[i].position`

#### Table 3 — Relevant Projects (2 cells per data row)

The frontend previously assumed 6 cells. The backend renders 2. Cell 1 is
heavily composite — 7 fields across multiple paragraphs in one cell. Cell 0 is
the `tasks_assigned` special case (see §5).

| cell_index | CVData field(s) | Composite? |
|------------|----------------|------------|
| 0 | `tasks_assigned` (special — see §5) | Special |
| 1 | `relevant_projects[i].project_name`, `relevant_projects[i].year`, `relevant_projects[i].location`, `relevant_projects[i].client`, `relevant_projects[i].main_project_features`, `relevant_projects[i].positions_held`, `relevant_projects[i].activities_performed` | **Yes — 7 fields** |

Cell 1 triggers the composite dropdown with seven options:
- `Project Name`          → `relevant_projects[i].project_name`
- `Year`                  → `relevant_projects[i].year`
- `Location`              → `relevant_projects[i].location`
- `Client`                → `relevant_projects[i].client`
- `Main Project Features` → `relevant_projects[i].main_project_features`
- `Positions Held`        → `relevant_projects[i].positions_held`
- `Activities Performed`  → `relevant_projects[i].activities_performed`

### 4.2 GIZ Table Layout

GIZ mapping is mostly aligned with the backend. The known composite edge cases:

- **Date range cells**: Some cells render a combined `date_from – date_to` string.
  Treat as composite; dropdown offers `Date From` and `Date To` as separate options
  mapping to `relevant_projects[i].date_from` and `relevant_projects[i].date_to`.
- **Countries of experience**: Rendered as a comma-separated list in a single
  cell. Not composite — map to `countries_of_experience` as a whole string.
- **Key qualifications**: Paragraph-based, no table. Map via paragraph index to
  `key_qualifications[paragraph_index]`. These are the most commonly edited
  fields and should work reliably without a dropdown.

GIZ does not require structural changes to the mapping logic — only the date
range composite edge case needs the dropdown treatment.

---

## 5. `tasks_assigned` Special Case (WB Only)

In the WB renderer (`templates/wb.py`), the content displayed in table 3, cell 0
is **not** a scalar at `relevant_projects[i].tasks_assigned` in CVData. It is
derived from `generated_fields["generated"]["generated_fields"]` — the list of
format-specific generated field entries — filtered to entries where
`field_key == "detailed_tasks"`, aligned by index to the relevant project row.

### Correct dot-path

When the user clicks table 3, cell 0, row `r` (project index `i = r - 1`):

The dot-path to pass to `POST /field-edit` is:
```
generated_fields[j].content
```
where `j` is the index of the matching `detailed_tasks` entry in the
`generated_fields` array.

### Frontend lookup logic

`GET /sessions/{id}/output` returns the full `cv_data` including the
`generated_fields` list. This call is already needed for the composite cell
dropdown (to know field values) so it should be fetched once when the
`completed` state is entered and cached for the session.

```typescript
function resolveTasksAssignedPath(
  generatedFields: GeneratedField[],
  projectIndex: number
): string | null {
  const detailedTaskEntries = generatedFields.filter(
    f => f.field_key === "detailed_tasks"
  );
  if (projectIndex < detailedTaskEntries.length) {
    const j = generatedFields.indexOf(detailedTaskEntries[projectIndex]);
    return `generated_fields[${j}].content`;
  }
  return null; // no matching entry — render cell as non-editable
}
```

If `j` cannot be resolved, show the cell as non-clickable (or show a tooltip
explaining it cannot be edited via this tool).

### Tooltip for `tasks_assigned`

Cell 0 in table 3 is not composite in the dropdown sense — it maps to a single
logical field (`tasks_assigned` / `detailed_tasks`). It does not need a field
selector dropdown. On click, go directly to the inline instruction input with the
resolved `generated_fields[j].content` path pre-filled.

### Backend compatibility

The `field_editor` agent resolves `generated_fields[j].content` via
`get_by_dot_path` against the `generated` object identically to any other scalar
path. No backend changes are required.

---

## 6. Composite Cell Dropdown — Behaviour Spec

### Trigger

When the user clicks a cell flagged as composite in the mapping table above, a
**tooltip** appears at the click position. The tooltip contains:

1. A labelled list of the fields that share this cell (all fields shown,
   regardless of whether the value is empty).
2. On selecting a field, the tooltip transitions inline to an instruction input
   for that field.

Non-composite cells skip the dropdown entirely — clicking opens the instruction
input directly.

### Inline instruction input (inside tooltip)

After a field is selected (or on direct click for non-composite cells):

```
[ Selected field label          ]   ← read-only, shows which field is targeted
[ Instruction text input        ]   ← user types their edit instruction here
[ Add to batch ]  [ Cancel ]
```

- `Add to batch`: validates that instruction is non-empty, adds
  `{ field_path, instruction }` to the batch accumulator, closes the tooltip.
  If the batch is already at 5 items, disable this button and show
  "Batch full (5/5)" instead.
- `Cancel`: closes the tooltip with no change to the batch.

### Batch accumulator

The batch accumulator is the existing edit list the user builds before
submitting `POST /field-edit`. Each entry added via the tooltip appends to this
list. The user can remove individual entries from the list before submitting.

The "Submit edits" button remains disabled until the batch has at least 1 entry.
It shows the current count (`Submit 3 edits`) up to the maximum of 5.

### Compatibility note

The inline instruction input inside the tooltip is the primary interaction. The
batch accumulator list below the DocxViewer (or in the side panel, depending on
layout) is the secondary view. Both must stay in sync — an entry added via the
tooltip appears immediately in the accumulator list, and removing it from the
accumulator list removes it from the pending batch.

---

## 7. `skipped` Edits — UI Handling

`POST /field-edit` returns `applied` and `skipped` arrays. Skipped edits mean
the agent could not apply the instruction — either the path was unresolvable or
the agent determined the instruction required fabricating information.

**What to show the user before the approval step:**

- If `skipped` is empty: show applied count and proceed to approval button.
- If `skipped` is non-empty: show a clear inline notice listing each skipped
  field path. Give the user two explicit choices:
  - **Approve anyway** — proceed to `POST /approve/checkpoint_3` accepting that
    skipped edits are absent from the re-rendered output.
  - **Cancel and re-edit** — do not approve; set status back to the edit panel
    view so the user can submit a corrected batch for the skipped fields.

Do not silently drop skipped edits. The user must make an explicit choice before
the re-render is triggered.

**Cancel and re-edit behaviour:**
Cancelling after a `skipped` result does not undo the `applied` edits — those
are already written to `generated_fields.json`. The user is re-editing from the
current state (with applied edits already in place). Make this clear in the UI
copy ("X edits were applied. The following Y edits were skipped — you can
re-submit instructions for the skipped fields.").

---

## 8. Deprecating `POST /comments` in the UI

Remove any UI element that triggers `POST /sessions/{id}/comments`:
- "Request a revision" buttons
- Free-text feedback inputs submitting to `/comments`

The field editor panel is the sole revision mechanism. The backend still accepts
`/comments` requests for backward compatibility but returns deprecation headers
— the frontend should not expose it.

---

## 9. Files to Modify

| File | Change |
|------|--------|
| `cv-drafter-ui/src/pages/SessionWorkspacePage.tsx` | Change trigger from `field_editor_pending` to `completed`; load `output.docx` via signed URL; add `GET /output` fetch on entry to `completed` state (cache for dropdown and `tasks_assigned` lookup); add post-edit polling loop; add checkpoint_3 approval UI with applied/skipped summary; remove `/comments` exposure |
| `cv-drafter-ui/src/lib/utils/locatorToDotPath.ts` | Rewrite WB table mapping to 3-cell employment and 2-cell projects layout; mark composite cells with field list metadata; add `tasks_assigned` resolution using `generated_fields` lookup; fix GIZ date range composite edge case |
| `cv-drafter-ui/src/components/DocxViewer.tsx` | On cell click: check if cell is composite → emit composite event with field list; if not composite → emit direct edit event with resolved path; add tooltip anchor point to click handler |
| `cv-drafter-ui/src/components/FieldSelectorTooltip.tsx` | **New component** — tooltip that renders field dropdown (if composite) → inline instruction input → Add to batch / Cancel |
| `cv-drafter-ui/src/lib/api.ts` | Ensure `fieldEdit` calls `POST /field-edit`; add `getOutput` function if not present; remove or mark deprecated `postComment` |
| `cv-drafter-ui/src/lib/types.ts` | Add `FieldEditRequest`, `FieldEditResponse`, `GeneratedField`, `CompositeCell` types if not present |

---

## 10. What Does Not Change

- `DocxViewer` structural XML parsing — locator generation (table/row/cell
  indices) is correct and does not need to change.
- Backend `field_editor` agent — handles `generated_fields[j].content` paths
  correctly with no modifications.
- Backend endpoint contract — `POST /field-edit` shape, validation, and
  response format are already aligned.
- `POST /resolve` — retained for `reviewer_blocked`; no changes needed there.
- GIZ template rendering — no backend changes; only `locatorToDotPath.ts`
  composite edge case handling changes on the frontend.
- WB template rendering — no backend changes.
