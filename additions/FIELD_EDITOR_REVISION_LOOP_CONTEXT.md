# Field Editor — Revision Loop Context

**Scope**: Post-completion revision loop only. This document is independent of
the pipeline diagnostic rounds (Rounds 1–7.5) and must not be treated as part
of any diagnostic round or fix sequence. The pipeline itself (Agents 1–6,
renderer, orchestrator) is stable. The issues described here exist entirely in
the layer between the rendered output document and the `POST /field-edit`
endpoint.

**Status at time of writing**: Round 7.5 complete, 461 tests passing. The
revision loop is currently non-functional end-to-end due to Issue A (blanket
400 error). Issues B–G are pre-existing structural bugs that surface once A
is resolved.

Cross-reference: `PIPELINE_CONTEXT.md`, `RENDERER_CONTEXT.md`,
`PROMPT_REVIEW_CONTEXT.md`, `RUNS_ARTIFACTS_CONTEXT.md`.

---

## 1. Revision loop architecture

The revision loop is the tail of the full pipeline. It is entered only after
the session reaches `completed` status (Phase 4 done, output `.docx` uploaded).

```
User clicks paragraph or cell in DocxViewer
    ↓
locatorToDotPath() resolves a dot-path (or fallback path)
    ↓
User types an instruction in FieldSelectorTooltip
    ↓
POST /sessions/{id}/field-edit
  { edits: [{ field_path, instruction, anchor_text }] }
    ↓
run_field_editor_task() (orchestrator, synchronous)
    ↓
field_editor.run() → run_field_editor() (sequential, one LLM call per edit)
    ↓
generated_fields.json["generated"] mutated in place
    ↓
session → checkpoint_3_pending
    ↓
POST /approve/checkpoint_3
    ↓
Phase 4 re-render → new output.docx uploaded (round_NN_giz.docx)
    ↓
session → completed
```

The loop may be re-entered at any round. Each `POST /field-edit` call
increments `sessions.round` and re-renders from the current state of
`generated_fields.json["generated"]`.

---

## 2. Renderer–field editor synchrony principle

This is a foundational constraint that all fixes must preserve and that no
future change may violate.

The GIZ renderer (`templates/giz.py → _build_context`) and the field editor
(`pipeline/agents/field_editor.py`) must always use the same priority when
resolving which data source provides a given field's displayed value. If the
renderer prefers source A over source B, the field editor must match against
source A's text and write to source A's path. Any divergence produces one of
two silent failure modes:

- **Skip**: the text match fails because the editor is comparing against the
  wrong source; the path falls back to `paragraph_N`; the backend cannot
  resolve it.
- **Silent no-op**: the text match partially succeeds; the path resolves to
  the wrong source; the write lands there; the renderer ignores it on the
  next render because it is still reading from the preferred source.

The shared `pipeline/utils/cefr.py` module (introduced in the mismatch fix
round) embodies this principle for CEFR values: a single source of truth
imported by both `templates/giz.py` and `field_editor.py`. Any future field
that requires a mapping or transformation at render time must follow this
same pattern — extract the logic into `pipeline/utils/`, import from both
the renderer and the field editor.

The backend currently satisfies this principle for all implemented fields
(`_key_qualification_bullets` priority, `_key_qualification_path_for_index`,
CEFR enrichment). The frontend does not yet satisfy it for key qualifications
(Issue D).

---

## 3. Current layer states

### 3a. Backend — `pipeline/agents/field_editor.py`

**Correct and complete:**

| Feature | Location | State |
|---|---|---|
| KQ bullet priority (generated_fields first, raw fallback) | `_key_qualification_bullets` | ✓ Correct |
| KQ path routing by active source | `_key_qualification_path_for_index` | ✓ Correct |
| Paragraph placeholder resolution | `resolve_paragraph_placeholder_path` | ✓ Correct |
| GIZ CEFR enrichment (blind-spot fix) | `run_field_editor` pre-Claude block | ✓ Correct |
| Non-rendered field redirect (GIZ `activities_performed`) | `_check_renderer_field` | ✓ Correct |
| Skip reasons as `list[dict]` with `path`/`reason` | `run_field_editor` + `run` | ✓ Correct |
| `kq_source` three-way label returned by `run()` | `kq_source_label` | ✓ Correct |

**Broken:**

`call_claude()` sends the request with the conversation ending on an
assistant-role message (the prefill). `claude-sonnet-4-6` does not support
this pattern. Every call returns HTTP 400. See Issue A.

### 3b. Backend — `api/models/requests.py`

Fully correct. `FieldEditSkip` (Pydantic model with `path: str`, `reason: str`)
is defined. `FieldEditResponse.skipped` is typed as `list[FieldEditSkip]`.
`kq_source` is a required `Literal["ai_generated", "extracted", "absent"]`
field on `FieldEditResponse`.

### 3c. Backend — `api/routers/sessions.py`

Fully correct. The route destructures the three-tuple `(applied, skipped,
kq_source)` from `run_field_editor_task` and forwards all values into
`FieldEditResponse`. `anchor_text` is correctly extracted from
`FieldEditItem` and forwarded in the edits dict.

### 3d. Frontend — `lib/utils/locatorToDotPath.ts`

Five bugs. See Issues B, C, D, E, F.

### 3e. Frontend — `components/DocxViewer.tsx`

One gap: `cvData` is not included in the `locatorDotPathOptions` memo.
See Issue G (coupled to Issue D and required by Issue C).

### 3f. Frontend — `lib/api.ts`

`submitFieldEdits()` returns JSON cast to `FieldEditResponse`. The frontend
type definition for `FieldEditResponse` does not include `kq_source`. The
backend sends it; the frontend drops it at the type boundary. This is an
accepted gap — `kq_source` is not currently consumed by any frontend logic.
It is documented here so it is not confused with a bug.

---

## 4. Issues

---

### Issue A — Prefill incompatibility (blanket 400 error)

**Classification**: Backend. Introduced during diagnostic rounds. Not
pre-existing.

**Root cause**

`call_claude()` in `field_editor.py` constructs the messages array as:

```python
messages=[
    {"role": "user",      "content": build_user_prompt(...)},
    {"role": "assistant", "content": ASSISTANT_PREFILL},  # ← illegal
]
```

`claude-sonnet-4-6` does not support assistant-turn prefill. The API returns:

```
HTTP 400 — invalid_request_error:
"This model does not support message prefill.
 The conversation must end with a user turn."
```

This error is caught by the `except Exception` block in `run_field_editor`,
which appends every edit to `skipped` with `"API or parse error: ..."`. No
edit can succeed regardless of path correctness.

**Why this was not caught during diagnostic rounds**

Agent 7 was explicitly out of scope during Rounds 1–7.5. The model constant
was changed as part of a broader model upgrade during those rounds. The
prefill behaviour was not re-validated after the model change.

**Fix**

Remove the assistant prefill entirely from `call_claude()`:

- Delete `ASSISTANT_PREFILL` constant.
- Remove the `{"role": "assistant", ...}` entry from the `messages` list.
- Remove the `full_response = ASSISTANT_PREFILL + continuation` assembly.
- Parse `raw.content[0].text` directly as `full_response`.

`SYSTEM_PROMPT_A7` already contains explicit, strong JSON format constraints
(`RESPONSE FORMAT` section, `DEFAULT: ALWAYS USE "apply"` block). No prompt
strengthening is required.

**Defensive JSON fence stripping — all agents**

Without the prefill, Claude may occasionally wrap its JSON response in
markdown code fences (` ```json ... ``` `). The current parser calls
`json.loads(full_response)` directly. A bare `json.loads` call will raise
`json.JSONDecodeError` on a fenced response.

A central utility function must be added to `pipeline/utils.py`:

```python
import re as _re

def strip_json_fences(text: str) -> str:
    """
    Remove markdown code fences from an LLM JSON response.

    Handles:
      ```json\n{...}\n```
      ```\n{...}\n```
      Bare {…} (returned unchanged)
    """
    stripped = text.strip()
    match = _re.match(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", stripped, _re.DOTALL)
    if match:
        return match.group(1).strip()
    return stripped
```

This function must be applied at the JSON parse site in every agent that calls
`json.loads` on an LLM response. Apply before `json.loads`, not after.

Agents to update (parse site in each):

| Agent | File | Parse site |
|---|---|---|
| A7 Field Editor | `pipeline/agents/field_editor.py` | `call_claude()` — `json.loads(full_response)` |
| A1 CV Extractor | `pipeline/agents/cv_extractor.py` | LLM response parse |
| A2 ToR Summarizer | `pipeline/agents/tor_summarizer.py` | LLM response parse |
| A3 CV-ToR Mapper | `pipeline/agents/cv_tor_mapper.py` | LLM response parse |
| A4 Fields Generator | `pipeline/agents/fields_generator.py` | LLM response parse |
| A5 Content Reviewer | `pipeline/agents/content_reviewer.py` | LLM response parse |
| A6 Compressor | `pipeline/agents/compressor.py` | LLM response parse |

Each agent's parse site should be updated to:
```python
from pipeline.utils import strip_json_fences
...
raw_text = strip_json_fences(raw.content[0].text)
parsed = json.loads(raw_text)
```

**Files to modify**

- `pipeline/utils.py` — add `strip_json_fences`
- `pipeline/agents/field_editor.py` — remove prefill; apply `strip_json_fences`
- `pipeline/agents/cv_extractor.py` — apply `strip_json_fences`
- `pipeline/agents/tor_summarizer.py` — apply `strip_json_fences`
- `pipeline/agents/cv_tor_mapper.py` — apply `strip_json_fences`
- `pipeline/agents/fields_generator.py` — apply `strip_json_fences`
- `pipeline/agents/content_reviewer.py` — apply `strip_json_fences`
- `pipeline/agents/compressor.py` — apply `strip_json_fences`

---

### Issue B — GIZ Table 3 row 0 hidden behind the dynamic-row header guard

**Classification**: Frontend. Pre-existing.

**Root cause**

`gizTableToDotPath` handles two categories of GIZ table:

- **Static tables** (0, 3): fixed rows, no dynamic expansion. Row indices
  correspond directly to data rows; there is no header row to skip.
- **Dynamic tables** (1, 2, 4, 5): expanded by the template preprocessor.
  Row 0 is always the header. Data rows start at row 1 → `array_index = row_index - 1`.

The function correctly handles table 0 in its own block before the header
guard. It then applies the guard unconditionally:

```typescript
const i = rowIndex - 1;
if (i < 0) return null; // intended for dynamic tables only
```

Table 3 is handled inside the switch that follows this guard. When the user
clicks row 0 of table 3 (`membership_professional_bodies`), `i` becomes -1,
the guard fires, and the function returns `null` — table 3's case is never
reached. The caller generates the fallback path `table_3_row_0_cell_1`.
The backend reports "path resolution failed."

Rows 2 and 3 of table 3 (`present_position`, `years_with_firm`) survive
because their `rowIndex > 0` passes the guard, and the table 3 switch
correctly uses `rowIndex` (not `i`) for its own dispatch — so those rows
have always worked.

**Failure mode**

`membership_professional_bodies` → frontend emits `table_3_row_0_cell_1` →
backend: `"path resolution failed: 'table_3_row_0_cell_1'"`.

**Fix**

Move the table 3 block above the `i` guard, parallel to the existing table 0
block. Table 3 uses `rowIndex` directly in its own switch, so no index
arithmetic changes are required. Only the structural position of the
`case 3` block changes.

**Note on template stability**

The row-to-field mapping for table 3 is declared in this document:
row 0 → `membership_professional_bodies`, row 1 → `other_skills`,
row 2 → `present_position`, row 3 → `years_with_firm`. If the GIZ template
ever adds or reorders rows in this table, `gizTableToDotPath` case 3 must be
updated to match. The fix is structured so that only the case 3 switch body
needs updating — the guard-free position is the correct structural home for
any static table.

**Files to modify**

- `cv-drafter-ui/src/lib/utils/locatorToDotPath.ts` — move case 3 above
  the `i` guard in `gizTableToDotPath`.

---

### Issue C — `other_skills` has no scalar path; cell produces a path resolution error with no user signal

**Classification**: Frontend. Pre-existing.

**Root cause**

`other_skills` in the CVData schema is `list[str]`, not a scalar.
`gizTableToDotPath` case 3 row 1 explicitly returns `null` because the field
cannot be edited as a single unit. When `null` is returned, the caller
generates the fallback path `table_3_row_1_cell_1`. The backend resolves this
path, finds no such key, and reports "path resolution failed." The user sees
an error with no explanation.

The cell is visually clickable but every interaction with it produces a
useless result.

**Fix**

Expose `other_skills` as a composite cell: one option per element in the
array, each targeting `other_skills[${n}]`.

This requires `cvData` to be available inside `gizTableToDotPath` at
resolution time (the array length and element labels must be read at runtime).
`cvData` is added to `LocatorToDotPathOptions` as part of Issue D/G — this
fix piggybacks on that.

**Behaviour when `cvData` is absent or `other_skills` is empty:**

Return `null`. The cell will be non-interactive (the same outcome as today,
but now it is the intended outcome rather than a silent fallthrough). The
visual disabled state should be applied by `DocxViewer`'s `isCellComposite`
helper, which already returns `false` for `null` results — no additional
change needed there.

**Renderer–field editor synchrony note**

The GIZ renderer joins `other_skills` with `"; "` to produce a single display
string: `other_skills_display = "; ".join(s.strip() for s in cv.get("other_skills", []) if s.strip())`.
The template renders this as one cell. A user editing `other_skills[0]`
changes a single element; the renderer recomputes the joined string on the
next render. This is consistent: the field editor writes to individual
elements, the renderer reads and joins all elements. No synchrony gap.

**Options shape (example for a 3-element `other_skills`)**

```typescript
{
  kind: "composite",
  dotPath: "",
  confidence: "mapped",
  label: "Skills",
  options: [
    { label: "Skill 1", dotPath: "other_skills[0]" },
    { label: "Skill 2", dotPath: "other_skills[1]" },
    { label: "Skill 3", dotPath: "other_skills[2]" },
  ],
}
```

**Files to modify**

- `cv-drafter-ui/src/lib/utils/locatorToDotPath.ts` — update case 3 row 1
  in `gizTableToDotPath` to build composite from `cvData?.other_skills`.
  Requires `cvData` in `LocatorToDotPathOptions` (Issue G).

---

### Issue D — KQ priority inversion in the frontend

**Classification**: Frontend. Pre-existing.

**Root cause**

The GIZ renderer (`templates/giz.py → _build_context`) resolves key
qualifications with this priority:

```
1. generated_fields entries where field_key == "key_qualifications"
   and content is non-empty  →  displayed in the output .docx
2. key_qualifications raw list as fallback
```

`effectiveKeyQualifications` in `locatorToDotPath.ts` uses the **opposite**
priority:

```typescript
// Current — WRONG
const top = cv.key_qualifications;       // checks raw list first
if (Array.isArray(top) && top.length > 0) { ... return coerced; }
// falls back to generated_fields
```

The backend `_key_qualification_bullets` already matches the renderer
(generated_fields first). The frontend does not.

**Failure modes**

When Agent 4 generates non-empty KQ content (the normal operating state once
the pipeline is producing real output):

- **Failure A — skip**: The `.docx` displays text from `generated_fields[j].content`.
  The user clicks it. `effectiveKeyQualifications` returns the raw
  `key_qualifications` list (different text). `matchKeyQualificationIndex`
  compares the generated text against the raw bullets — score below threshold.
  Path falls back to `paragraph_N`. Backend `resolve_paragraph_placeholder_path`
  runs the same comparison (backend uses the correct priority, but anchor text
  was already matched against the wrong source by the frontend). If no match,
  the path stays `paragraph_N`. `get_by_path` raises `KeyError`. Edit is skipped.

- **Failure B — silent no-op**: Texts partially overlap enough for a match.
  Path resolves to `key_qualifications[i]`. Field editor writes the new value
  there. On the next render, `_build_context` finds non-empty `generated_fields`
  entries and uses those, ignoring `key_qualifications` entirely. The re-rendered
  `.docx` is unchanged. The edit is in `applied` but is a silent no-op.

These failures do not surface on sessions where Agent 4 produced all-empty
`generated_fields` content — in that state, both layers fall back to the raw
list and agree. They become systematic the moment A4 generates real KQ content.

**Fix**

Reverse priority in `effectiveKeyQualifications`:

```typescript
export function effectiveKeyQualifications(cv: CVDataLite | undefined): string[] {
  if (!cv) return [];
  // 1. generated_fields content (non-empty) — matches renderer priority
  const gf = cv.generated_fields;
  if (Array.isArray(gf)) {
    const fromGf = gf
      .filter((f): f is GeneratedField =>
        f.field_key === "key_qualifications" &&
        typeof f.content === "string" &&
        f.content.trim().length > 0)
      .map((f) => f.content.trim());
    if (fromGf.length > 0) return fromGf;
  }
  // 2. raw key_qualifications list as fallback
  const top = cv.key_qualifications;
  if (Array.isArray(top)) {
    const coerced = top.map((x) => String(x).trim()).filter(Boolean);
    if (coerced.length > 0) return coerced;
  }
  return [];
}
```

Add `resolveKeyQualificationsPath` — returns the `generated_fields[j].content`
path for bullet at `bulletIndex` when GF is the active source, or `null` when
the raw list is active (caller falls back to `key_qualifications[bulletIndex]`):

```typescript
export function resolveKeyQualificationsPath(
  generatedFields: GeneratedField[] | undefined,
  bulletIndex: number,
): string | null {
  if (!generatedFields) return null;
  const kqEntries = generatedFields.filter(
    (f): f is GeneratedField =>
      f.field_key === "key_qualifications" &&
      typeof f.content === "string" &&
      f.content.trim().length > 0,
  );
  if (kqEntries.length === 0 || bulletIndex >= kqEntries.length) return null;
  const j = generatedFields.indexOf(kqEntries[bulletIndex]);
  if (j === -1) return null;
  return `generated_fields[${j}].content`;
}
```

Update the paragraph branch in `locatorToDotPath` to use
`resolveKeyQualificationsPath` when GF is the active source:

```typescript
if (kqIdx !== null) {
  const kqPath =
    resolveKeyQualificationsPath(options?.cvData?.generated_fields, kqIdx) ??
    `key_qualifications[${kqIdx}]`;
  return {
    kind: "simple",
    dotPath: kqPath,
    confidence: "mapped",
    label: `Key qualification ${kqIdx + 1}`,
  };
}
```

**Renderer–field editor synchrony note**

After this fix, the three layers share one priority:
- **Renderer** (`giz.py`): generated_fields first, raw fallback ✓ (unchanged)
- **Backend field editor** (`field_editor.py → _key_qualification_bullets`): generated_fields first, raw fallback ✓ (already correct)
- **Frontend** (`locatorToDotPath.ts → effectiveKeyQualifications`): generated_fields first, raw fallback ✓ (fixed here)

All three layers use `generated_fields[j].content` paths when GF is active
and `key_qualifications[i]` paths when the raw list is the fallback. No layer
will write to a path the renderer ignores.

**Files to modify**

- `cv-drafter-ui/src/lib/utils/locatorToDotPath.ts` — reverse
  `effectiveKeyQualifications`; add `resolveKeyQualificationsPath`; update
  paragraph branch.

---

### Issue E — WB employment record cell 0 maps to non-existent field `period`

**Classification**: Frontend. Pre-existing.

**Root cause**

`wbTableToDotPath` case 2 cell 0 currently emits:

```typescript
dotPath: `employment_record[${i}].period`
```

`period` does not exist as a persisted field on `EmploymentRecord`. It is a
computed display string assembled at render time in `templates/wb.py`:

```python
if from_date and to_date:
    period = f"{from_date} – {to_date}"
else:
    period = from_date or to_date
# injected into template context as employment_record[i].period
```

The field exists only in the Jinja template context, not in `generated_fields.json`.
`get_by_path` raises `KeyError` on every click of an employment period cell.

**Fix**

Make cell 0 a composite with the two underlying persisted fields:

```typescript
if (cellIndex === 0)
  return {
    kind: "composite",
    dotPath: "",
    confidence: "mapped",
    label: `Employment ${i + 1} — period`,
    options: [
      { label: "Date From", dotPath: `employment_record[${i}].from_date` },
      { label: "Date To",   dotPath: `employment_record[${i}].to_date`   },
    ],
  };
```

Both `from_date` and `to_date` exist as scalar string fields on
`EmploymentRecord` in the Pydantic model. No backend changes required.

**Files to modify**

- `cv-drafter-ui/src/lib/utils/locatorToDotPath.ts` — update case 2 cell 0
  in `wbTableToDotPath`.

---

### Issue F — WB employment record cell 1 uses wrong field name `position`

**Classification**: Frontend. Pre-existing.

**Root cause**

`wbTableToDotPath` case 2 cell 1 is a composite with:

```typescript
{ label: "Position", dotPath: `employment_record[${i}].position` },
```

The field `position` does not exist on `EmploymentRecord`. The correct field
name is `positions_held`. `get_by_path` raises `KeyError` on every attempt
to edit the position option.

`employer` in the same composite is correct — `employer` exists as a scalar
on `EmploymentRecord`.

**Fix**

```typescript
{ label: "Position", dotPath: `employment_record[${i}].positions_held` },
```

**Files to modify**

- `cv-drafter-ui/src/lib/utils/locatorToDotPath.ts` — update the `position`
  option in case 2 cell 1 composite in `wbTableToDotPath`.

---

### Issue G — `cvData` absent from `locatorDotPathOptions` memo

**Classification**: Frontend. Pre-existing. Coupled to Issues C and D.

**Root cause**

`DocxViewer.tsx` computes `locatorDotPathOptions` in a `useMemo`:

```typescript
const locatorDotPathOptions = useMemo((): LocatorToDotPathOptions => {
  const kq = effectiveKeyQualifications(cvData);
  const ori = effectiveOtherRelevantInfo(cvData);
  const opts: LocatorToDotPathOptions = {};
  if (kq.length > 0) opts.keyQualifications = kq;
  if (ori) opts.otherRelevantInfo = ori;
  if (blocks.length > 0) {
    opts.docBlocks = blocks.map(...);
  }
  return opts;
}, [cvData, targetFormat, blocks]);
```

`cvData` is used to extract the text values of `keyQualifications` and
`otherRelevantInfo`, but the raw `cvData` struct is never included in the
options object itself. `LocatorToDotPathOptions` has no `cvData` field.

This means:
- The paragraph branch of `locatorToDotPath` cannot determine the active KQ
  source — `resolveKeyQualificationsPath` cannot be called (Issue D requires it).
- `gizTableToDotPath` cannot read `other_skills` to build the composite
  (Issue C requires it).

**Fix**

Add `cvData?: CVDataLite` to `LocatorToDotPathOptions`:

```typescript
export type LocatorToDotPathOptions = {
  keyQualifications?: string[];
  docBlocks?: KqDocBlock[];
  otherRelevantInfo?: string;
  cvData?: CVDataLite;          // ← added
};
```

Pass `cvData` into the memo's options object in `DocxViewer.tsx`:

```typescript
const locatorDotPathOptions = useMemo((): LocatorToDotPathOptions => {
  const kq = effectiveKeyQualifications(cvData);
  const ori = effectiveOtherRelevantInfo(cvData);
  const opts: LocatorToDotPathOptions = {};
  if (kq.length > 0) opts.keyQualifications = kq;
  if (ori) opts.otherRelevantInfo = ori;
  if (cvData) opts.cvData = cvData;   // ← added
  if (blocks.length > 0) {
    opts.docBlocks = blocks.map(...);
  }
  return opts;
}, [cvData, targetFormat, blocks]);
```

Update `gizTableToDotPath` signature to accept `cvData`:

```typescript
function gizTableToDotPath(
  tableIndex: number,
  rowIndex: number,
  cellIndex: number,
  cvData?: CVDataLite,   // ← added
): LocatorMappingResult | null
```

Forward `cvData` from `locatorToDotPath` into `gizTableToDotPath` when
dispatching GIZ table clicks.

**Files to modify**

- `cv-drafter-ui/src/lib/utils/locatorToDotPath.ts` — add `cvData` to
  `LocatorToDotPathOptions`; update `gizTableToDotPath` signature; forward
  from `locatorToDotPath`.
- `cv-drafter-ui/src/components/DocxViewer.tsx` — add `cvData` to memo options.

---

## 5. Implementation order

Issues are coupled in two ways: A is independent and must be fixed first
(nothing else matters while all calls return 400). C and D both require G
to be done first. E and F are independent of each other and of everything else.

Recommended sequence:

```
1. Issue A  — remove prefill; add strip_json_fences to all agents
2. Issue G  — add cvData to LocatorToDotPathOptions and DocxViewer memo
3. Issue D  — reverse KQ priority; add resolveKeyQualificationsPath
4. Issue C  — other_skills composite (now cvData is available)
5. Issue B  — move table 3 above the header guard
6. Issues E & F  — WB employment field name fixes (independent; can be done at any point after A)
```

---

## 6. Files to modify — full summary

| File | Issues addressed |
|---|---|
| `pipeline/utils.py` | A — add `strip_json_fences` |
| `pipeline/agents/field_editor.py` | A — remove prefill; apply `strip_json_fences` |
| `pipeline/agents/cv_extractor.py` | A — apply `strip_json_fences` |
| `pipeline/agents/tor_summarizer.py` | A — apply `strip_json_fences` |
| `pipeline/agents/cv_tor_mapper.py` | A — apply `strip_json_fences` |
| `pipeline/agents/fields_generator.py` | A — apply `strip_json_fences` |
| `pipeline/agents/content_reviewer.py` | A — apply `strip_json_fences` |
| `pipeline/agents/compressor.py` | A — apply `strip_json_fences` |
| `cv-drafter-ui/src/lib/utils/locatorToDotPath.ts` | B, C, D, E, F, G |
| `cv-drafter-ui/src/components/DocxViewer.tsx` | G |

---

## 7. What is NOT changed by these fixes

- `SYSTEM_PROMPT_A7` — no changes. Current prompt is sufficient without prefill.
- `templates/giz.py` — no changes. Renderer priority is correct.
- `templates/wb.py` — no changes covered by this document.
- `pipeline/utils/cefr.py` — no changes. Shared CEFR map is correct.
- `pipeline/orchestrator.py` — no changes.
- `api/routers/sessions.py` — no changes.
- `api/models/requests.py` — no changes.
- The `applied` list shape — still `list[str]`.
- The `skipped` list shape — still `list[dict]` with `path`/`reason`.
- The `kq_source` field on `FieldEditResponse` — backend sends it; frontend
  does not consume it. No change to either side.
- Any pipeline diagnostic round fix — all Round 1–7.5 changes are unaffected.
