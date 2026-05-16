# Field Editor — Source-of-Truth Mismatches & Correct Behaviour

Single reference for the gaps found between the GIZ renderer (`templates/giz.py`),
the frontend path resolver (`lib/utils/locatorToDotPath.ts`), and the backend
field editor agent (`pipeline/agents/field_editor.py`).

Each mismatch is described as: what each layer currently does, why they
disagree, the failure mode that results, and the correct behaviour all three
must converge on.

---

## 1. GIZ Key Qualifications — Priority Inversion

### What each layer currently does

**Renderer (`giz.py → _build_context`)**
```python
generated_kq = [
    gf.get("content", "").strip()
    for gf in cv.get("generated_fields", [])
    if gf.get("field_key") == "key_qualifications" and gf.get("content", "").strip()
]
extracted_kq = [kq.strip() for kq in cv.get("key_qualifications", []) if kq.strip()]
key_qualifications = generated_kq if generated_kq else extracted_kq
```

Priority: **`generated_fields[j].content` (non-empty) → `key_qualifications[i]`**

The context variable `key_qualifications` fed to the Jinja template is a flat
list built from whichever source is non-empty first. The template accesses it
as `{{ key_qualifications[0] }}`, `{{ key_qualifications[1] }}`, etc.

---

**Frontend (`effectiveKeyQualifications` in `locatorToDotPath.ts`)**
```typescript
const top = cv.key_qualifications;
if (Array.isArray(top) && top.length > 0) {
  const coerced = top.map((x) => String(x).trim()).filter(Boolean);
  if (coerced.length > 0) return coerced;
}
// falls back to generated_fields entries
```

Priority: **`key_qualifications[i]` → `generated_fields[j].content`**

This list is what `matchKeyQualificationIndex` compares against clicked
paragraph text. The path emitted is always `key_qualifications[i]`.

---

**Backend field editor (`_key_qualification_bullets` in `field_editor.py`)**
```python
raw = generated.get("key_qualifications")
if isinstance(raw, list) and raw:
    out = [str(x).strip() for x in raw if str(x).strip()]
    if out:
        return out
# falls back to generated_fields entries
```

Priority: **`key_qualifications[i]` → `generated_fields[j].content`**

This list is what `resolve_paragraph_placeholder_path` uses for text-matching
when a `paragraph_N` fallback path arrives from the frontend.

---

### Why they disagree

The renderer was designed to prefer LLM-generated content (`generated_fields`)
over extracted content (`key_qualifications`). The frontend and backend resolver
were written with the opposite priority — favouring the extracted list first.

They only agree when `generated_fields` entries for key_qualifications are all
empty (which is what the current sample session shows). In that state the
renderer falls back to `key_qualifications`, matching the frontend, and edits
work end-to-end. But this is the fallback state, not the normal operating state
once Agent 4 is producing content.

---

### Failure modes (when Agent 4 generates non-empty `generated_fields` content)

**Failure A — path resolution fails at the frontend match step**

The `.docx` displays the text from `generated_fields[j].content` (renderer
priority). The user clicks a paragraph; `text_content` is that generated text.
`effectiveKeyQualifications` returns the `key_qualifications` raw list (different
text). `matchKeyQualificationIndex` compares the generated text against the raw
bullets — match score falls below threshold. Path falls back to `paragraph_N`.
The backend `resolve_paragraph_placeholder_path` runs the same comparison with
`_key_qualification_bullets` (also raw list first) — same mismatch — stays
`paragraph_N`. `get_by_path(mutated, "paragraph_N")` raises `KeyError`. Edit
lands in `skipped` with reason "path resolution failed."

**Failure B — path resolves but write has no effect on rendered output**

If the texts overlap enough to match (partial word overlap), the path resolves
to `key_qualifications[i]`. The field editor writes the new value there. The
next render runs `_build_context`, finds non-empty `generated_fields` entries,
uses those, and ignores `key_qualifications` entirely. The re-rendered `.docx`
is unchanged. The edit is in `applied` but is silently a no-op.

---

### Correct behaviour

The renderer's priority is authoritative — it controls what appears in the
output document. The frontend and backend must align to it.

**Rule**: When `generated_fields` has at least one entry with
`field_key == "key_qualifications"` and non-empty `content`, that list is the
source of truth for both path generation and text matching. When all such entries
are empty or absent, fall back to `key_qualifications`.

**Frontend — `effectiveKeyQualifications`**

Reverse the priority to match the renderer:

```typescript
export function effectiveKeyQualifications(cv: CVDataLite | undefined): string[] {
  if (!cv) return [];
  const gf = cv.generated_fields;
  if (Array.isArray(gf)) {
    const fromGf = gf
      .filter((f): f is GeneratedField =>
        f.field_key === "key_qualifications" &&
        typeof f.content === "string" &&
        f.content.trim().length > 0,
      )
      .map((f) => f.content.trim());
    if (fromGf.length > 0) return fromGf;
  }
  const top = cv.key_qualifications;
  if (Array.isArray(top)) {
    const coerced = top.map((x) => String(x).trim()).filter(Boolean);
    if (coerced.length > 0) return coerced;
  }
  return [];
}
```

**Frontend — path generation**

When the active source is `generated_fields`, the emitted path must be
`generated_fields[j].content` — the actual write target the renderer reads
from — not `key_qualifications[i]`.

Add a `resolveKeyQualificationsPath` function parallel to the existing
`resolveTasksAssignedPath` (which already implements this correctly for WB
`detailed_tasks`):

```typescript
export function resolveKeyQualificationsPath(
  generatedFields: GeneratedField[] | undefined,
  bulletIndex: number,
): string | null {
  if (!generatedFields) return null;
  const kqEntries = generatedFields.filter(
    (f) => f.field_key === "key_qualifications" && f.content.trim().length > 0,
  );
  if (bulletIndex >= kqEntries.length) return null;
  const j = generatedFields.indexOf(kqEntries[bulletIndex]);
  if (j === -1) return null;
  return `generated_fields[${j}].content`;
}
```

In the paragraph branch of `locatorToDotPath`: after `matchKeyQualificationIndex`
returns an index, check whether `generated_fields` is the active source. If yes,
call `resolveKeyQualificationsPath` to get the `generated_fields[j].content`
path. If no (raw list is the fallback source), keep `key_qualifications[i]`.

**Backend — `_key_qualification_bullets`**

Reverse the priority to match the renderer:

```python
def _key_qualification_bullets(generated: dict) -> list[str]:
    gf = generated.get("generated_fields")
    if isinstance(gf, list):
        out = [
            str(e.get("content", "")).strip()
            for e in gf
            if isinstance(e, dict)
            and e.get("field_key") == "key_qualifications"
            and str(e.get("content", "")).strip()
        ]
        if out:
            return out
    raw = generated.get("key_qualifications")
    if isinstance(raw, list) and raw:
        out = [str(x).strip() for x in raw if str(x).strip()]
        if out:
            return out
    return []
```

The path emitted by the frontend (`generated_fields[j].content`) resolves and
writes correctly via the existing `get_by_path` / `set_by_path` machinery —
no changes needed there.

---

## 2. WB Employment Record — Wrong Field Names

### What the frontend currently does

`locatorToDotPath.ts` maps WB Table 2 (Employment Record) as follows:

```typescript
// cell 0:
dotPath: `employment_record[${i}].period`

// cell 1 composite:
options: [
  { label: "Employer", dotPath: `employment_record[${i}].employer` },
  { label: "Position", dotPath: `employment_record[${i}].position` },
]

// cell 2:
dotPath: `employment_record[${i}].country`
```

### What the CVData model actually defines

`EmploymentRecord` in `models.py`:

```python
class EmploymentRecord(BaseModel):
    from_date: str      # ← not "period"
    to_date: str        # ← not "period"
    employer: str       # ✓ correct
    location: str
    country: str        # ✓ correct
    positions_held: str # ← not "position"
    description: str
```

### Failure mode

`employment_record[i].period` and `employment_record[i].position` do not exist
in `generated`. `get_by_path` raises `KeyError` for both. Both edits land in
`skipped` with reason "path resolution failed." This affects every WB session
for every employment record row — a systematic 100% skip rate for those two
cell types regardless of instruction.

### Correct behaviour

Fix the frontend path mappings to use the actual model field names:

```typescript
// cell 0 — period is a composite of two separate date fields
if (cellIndex === 0)
  return {
    kind: "composite",
    dotPath: "",
    confidence: "mapped",
    label: `Employment ${i + 1} — period`,
    options: [
      { label: "From", dotPath: `employment_record[${i}].from_date` },
      { label: "To",   dotPath: `employment_record[${i}].to_date`   },
    ],
  };

// cell 1 composite — position corrected
options: [
  { label: "Employer", dotPath: `employment_record[${i}].employer`       },
  { label: "Position", dotPath: `employment_record[${i}].positions_held` },
]
```

No backend changes needed — `from_date`, `to_date`, and `positions_held` exist
in `generated` and the path resolver handles them correctly.

---

## 3. GIZ Languages — CEFR Resolution Blind Spot

### What each layer currently does

**Renderer (`giz.py → _resolve_cefr`)**
```python
def _resolve_cefr(entry: dict, cefr_field: str, raw_field: str) -> str:
    cefr = entry.get(cefr_field, "").strip()
    if cefr:
        return cefr
    raw = entry.get(raw_field, "").strip()
    return _map_cefr(raw) if raw else ""
```

The renderer checks `reading_cefr` first. If empty, it maps `reading_raw`
to CEFR and displays the result. The displayed CEFR value in the `.docx` may
therefore come from `reading_raw` even though the template cell references
`{{ languages[i].reading_cefr }}`.

**Frontend**: maps cells to `languages[i].reading_cefr`, `speaking_cefr`,
`writing_cefr`.

**Backend field editor**: receives `current_value = ""` when `reading_cefr` is
empty — which is the case for any session where the extractor populated only
`reading_raw` (common when the source CV already uses CEFR notation or
free-text like "mother tongue").

### Failure mode

This is not a skip. The edit lands in `applied` and the next render uses the
written `reading_cefr` value correctly. However the agent is editing blind: it
receives an empty `current_value` while the document displays a mapped value
derived from `reading_raw`. The user's instruction ("change to B2") is applied
against an empty field, which works, but the agent cannot see or reason about
the value the user actually wanted to change.

Additionally, after the edit `reading_cefr` is set to the new value while
`reading_raw` still holds the old raw string. The renderer will use
`reading_cefr` on all future renders, so the stale `reading_raw` is harmless
but inconsistent.

### Correct behaviour

**Option A — agent sees the displayed value (recommended)**

In `build_user_prompt`, when `donor == "giz"` and the resolved `field_key`
is one of `reading_cefr`, `speaking_cefr`, `writing_cefr`, and `current_value`
is empty, look up the corresponding raw field from `generated` and apply the
same CEFR mapping the renderer uses. Pass the rendered display value as
`current_value` so the agent edits from the actual displayed state.

This requires `build_user_prompt` to receive the full `generated` dict (or a
pre-resolved display value) in addition to the raw `current_value`. The
orchestrator already has access to `generated` when calling `run_field_editor`.

**Option B — data hygiene after write**

After writing a new value to `reading_cefr`, also overwrite `reading_raw` with
the same value. This keeps both fields consistent and prevents future confusion.
Can be handled as a post-write hook in `run_field_editor` for any CEFR field.

Option A corrects agent behaviour immediately. Option B is a data consistency
improvement that can be implemented independently.

---

## 4. GIZ Education — Combined Display vs. Raw Field Edit

### What the renderer does

`_build_context` combines institution and date range into a single display
string:

```python
"institution": (f"{institution} [{date_range}]" if date_range else institution)
```

The template renders `{{ education[0].institution }}` as e.g.
`"University of Pretoria [2011 – 2016]"`.

### What the frontend generates

GIZ Table 1 cell 0 is a composite with options for `education[i].institution`,
`education[i].date_from`, and `education[i].date_to`.

### Behaviour

Not a skip. All three paths exist in `generated` as scalars and resolve
correctly. The field editor writes to the raw field. The next render recomputes
the combined display string from the updated value.

One UX note: the agent receives `current_value = "University of Pretoria"` (raw
name, without dates) while the user saw the combined `"University of Pretoria
[2011 – 2016]"` in the document. This could cause confusion if the instruction
references the date portion. However this is a display convention, not a code
bug, and no code changes are required.

---

## Summary Table

| # | Scope | Layers affected | Failure mode | Fix required |
|---|-------|-----------------|--------------|--------------|
| 1 | GIZ key qualifications | Renderer vs. frontend vs. backend | Systematic skip (path mismatch) + silent no-op (wrong write target) when `generated_fields` has non-empty content | Frontend: reverse `effectiveKeyQualifications` priority; emit `generated_fields[j].content` paths via `resolveKeyQualificationsPath`. Backend: reverse `_key_qualification_bullets` priority. |
| 2 | WB employment record | Frontend only | 100% skip rate for `period` and `position` cells — field names do not exist in CVData | Frontend: fix `period` → composite `from_date`/`to_date`; fix `position` → `positions_held`. |
| 3 | GIZ languages CEFR | Backend prompt context | No skip; agent edits blind when `reading_cefr` is empty while document displays mapped `reading_raw` value | Backend: pass rendered display value as `current_value` when CEFR field is empty (Option A). |
| 4 | GIZ education combined display | Renderer only | No skip; edit applies correctly, renderer recomputes combined string | No fix required. |

---

## Files to Modify

| File | Change |
|------|--------|
| `lib/utils/locatorToDotPath.ts` | Reverse `effectiveKeyQualifications` priority; add `resolveKeyQualificationsPath`; update paragraph branch to emit `generated_fields[j].content` when source is `generated_fields`; fix WB employment record cell 0 → composite (`from_date`/`to_date`); fix cell 1 `position` → `positions_held` |
| `pipeline/agents/field_editor.py` | Reverse `_key_qualification_bullets` priority (non-empty `generated_fields` first); optionally enrich `current_value` for GIZ CEFR fields when stored value is empty (Mismatch 3, Option A) |
| `pipeline/orchestrator.py` | No changes required |
| `templates/giz.py` | No changes required |

---

## 5. WB Detailed Tasks — Index Misalignment Between Renderer and Frontend

### What each layer currently does

**Renderer (`wb.py → _build_context`)**
```python
detailed_tasks = [
    gf.get("content", "").strip()
    for gf in cv.get("generated_fields", [])
    if gf.get("field_key") == "detailed_tasks" and gf.get("content", "").strip()
]

relevant_projects = []
for i, proj in enumerate(cv.get("relevant_projects", [])):
    relevant_projects.append({
        "tasks_assigned": detailed_tasks[i] if i < len(detailed_tasks) else "",
        ...
    })
```

The renderer filters `generated_fields` to only non-empty `detailed_tasks`
entries, then assigns index `i` of that filtered list to project `i`.

**Frontend (`resolveTasksAssignedPath` in `locatorToDotPath.ts`)**
```typescript
const detailedTaskEntries = generatedFields.filter(
  (f) => f.field_key === "detailed_tasks",
);
if (projectIndex >= detailedTaskEntries.length) return null;
const j = generatedFields.indexOf(detailedTaskEntries[projectIndex]);
return `generated_fields[${j}].content`;
```

The frontend filters on `field_key === "detailed_tasks"` only — no content
check. `projectIndex` is `row_index - 1` from the WB Relevant Projects table,
i.e. the data row ordinal, directly matching `relevant_projects[i]`.

### Why they disagree

Both layers use `projectIndex` as an ordinal into their respective
`detailed_tasks` lists, but those lists have different lengths whenever any
`generated_fields` entry has empty content.

Example — 4 `detailed_tasks` entries where entry 1 is empty:

| j (full array) | content | Renderer's filtered list | Frontend's unfiltered list |
|---|---|---|---|
| 0 | "Task A" | index 0 → project 0 ✓ | index 0 → project 0 ✓ |
| 1 | "" | skipped | index 1 → project 1 |
| 2 | "Task C" | index 1 → project 1 ✗ | index 2 → project 2 |
| 3 | "Task D" | index 2 → project 2 ✗ | index 3 → project 3 |

The renderer assigns Task C to project 1; the frontend targets
`generated_fields[2].content` for project 2. Every write from project 1
onwards lands on the wrong slot in the rendered output.

### Failure mode

Not a skip — the edit lands in `applied` and writes to the correct
`generated_fields[j].content` path. But the renderer assigns that slot to a
different project, so the written content appears under the wrong project in
the re-rendered `.docx`. For sessions where all entries are empty (as in the
sample WB session), both lists are length zero so the misalignment doesn't
surface — but it becomes active the moment Agent 4 generates any partial
content.

### Correct behaviour

The renderer's filter is the source of misalignment. Removing it makes both
layers index the same unfiltered `detailed_tasks` list. Empty entries render
as empty cells, which is correct — it signals no task was generated for that
project and makes the cell available for a field edit to populate.

**Fix — `wb.py → _build_context` only:**

```python
# Remove the non-empty content filter
detailed_tasks = [
    gf.get("content", "").strip()
    for gf in cv.get("generated_fields", [])
    if gf.get("field_key") == "detailed_tasks"
]
```

No changes needed in `locatorToDotPath.ts` or `field_editor.py`.

---

## 6. WB Renderer — Missing Context Keys

### What the template uses vs. what `_build_context` returns

The WB dynamic template references the following variables that `_build_context`
in `wb.py` does not include in its return dict:

| Template variable | Present in `_build_context` return? |
|---|---|
| `{{ employer }}` | ✗ absent |
| `{{ membership_professional_bodies }}` | ✗ absent |
| `{{ countries_display }}` | ✗ absent |
| `{{ other_skills_display }}` | ✗ absent |

### Failure mode

Field edits to `employer` and `membership_professional_bodies` resolve
correctly in `generated` (both are scalar strings in CVData) and land in
`applied`. But at render time, the template variable is unpopulated — docxtpl
renders it as an empty string regardless of what the field editor wrote. Silent
no-op on re-render.

`countries_display` and `other_skills_display` are computed display strings
(not direct CVData paths), so the frontend correctly does not generate editable
paths for them. They are documented here for completeness since their absence
from `_build_context` would cause empty template cells.

### Correct behaviour

Add the missing keys to `_build_context`'s return dict in `wb.py`:

```python
# Computed display strings — same pattern as giz.py
countries_display = ", ".join(
    ce.get("country", "").strip()
    for ce in cv.get("countries_of_experience", [])
    if ce.get("country", "").strip()
)
other_skills_display = "; ".join(
    s.strip() for s in cv.get("other_skills", []) if s.strip()
)

return {
    ...
    "employer": cv.get("employer", "").strip(),
    "membership_professional_bodies": cv.get("membership_professional_bodies", "").strip(),
    "countries_display": countries_display,
    "other_skills_display": other_skills_display,
    ...
}
```

No frontend or field editor changes needed.

---

## 7. WB Languages — No Mismatch

WB uses `reading_raw`, `speaking_raw`, `writing_raw` directly in both the
renderer and the frontend path mapping. The renderer passes these fields
straight to the template without any CEFR conversion. The field editor writes
to the same paths. All three layers are consistent.

Mismatch 3 (GIZ CEFR blind spot) does not apply to WB. No fix required.

---

## Updated Summary Table

| # | Format | Scope | Layers affected | Failure mode | Fix required |
|---|---|-------|-----------------|--------------|--------------|
| 1 | GIZ | Key qualifications priority inversion | Renderer vs. frontend vs. backend | Systematic skip + silent no-op when `generated_fields` has non-empty content | Frontend: reverse `effectiveKeyQualifications` priority; emit `generated_fields[j].content` paths. Backend: reverse `_key_qualification_bullets` priority. |
| 2 | Both | Employment record wrong field names | Frontend only | 100% skip for `period` and `position` cells | Frontend: fix `period` → composite `from_date`/`to_date`; fix `position` → `positions_held`. |
| 3 | GIZ | Languages CEFR blind spot | Backend prompt context | No skip; agent edits blind when `reading_cefr` empty | Backend: pass rendered display value as `current_value` when CEFR field is empty (Option A). |
| 4 | GIZ | Education combined display | Renderer only | No skip; works correctly | No fix required. |
| 5 | WB | Detailed tasks index misalignment | Renderer only | Edit applied to correct slot but renders under wrong project | `wb.py`: remove non-empty content filter from `detailed_tasks` list comprehension. |
| 6 | WB | Missing context keys | Renderer only | `employer` and `membership_professional_bodies` edits are silent no-ops | `wb.py`: add missing keys to `_build_context` return dict. |
| 7 | WB | Languages raw fields | — | No mismatch | No fix required. |

---

## Updated Files to Modify

| File | Changes |
|------|---------|
| `lib/utils/locatorToDotPath.ts` | Reverse `effectiveKeyQualifications` priority; add `resolveKeyQualificationsPath`; update paragraph branch to emit `generated_fields[j].content` when source is `generated_fields`; fix WB employment record cell 0 → composite (`from_date`/`to_date`); fix cell 1 `position` → `positions_held` |
| `pipeline/agents/field_editor.py` | Reverse `_key_qualification_bullets` priority; enrich `current_value` for GIZ CEFR fields when stored value is empty (Mismatch 3, Option A) |
| `templates/wb.py` | Remove non-empty filter from `detailed_tasks` list comprehension (Mismatch 5); add `employer`, `membership_professional_bodies`, `countries_display`, `other_skills_display` to `_build_context` return dict (Mismatch 6) |
| `pipeline/orchestrator.py` | No changes required |
| `templates/giz.py` | No changes required |
