# Field Editor Mismatch Fixes — Implementation Record

Reference: `FIELD_EDITOR_MISMATCH_CONTEXT.md` (same directory) describes every
mismatch in detail.  This document records what was changed, why each decision
was made, and what the code looks like after the fix.

---

## Overview

Six mismatches were identified between the GIZ/WB renderers, the frontend path
resolver, and the backend field editor.  Four required code changes (mismatches
1, 2, 3, 5, 6).  Two required no action (mismatches 4, 7).

| # | Format | Mismatch | Fix type |
|---|--------|----------|----------|
| 1 | GIZ | KQ priority inversion | Backend + Frontend |
| 2 | Both | Employment record wrong field names | Frontend only |
| 3 | GIZ | CEFR blind spot | Backend only |
| 4 | GIZ | Education combined display | No fix required |
| 5 | WB | Detailed tasks index misalignment | Backend only |
| 6 | WB | Missing context keys in renderer | Backend only |
| 7 | WB | Languages raw fields | No fix required |

---

## Shared infrastructure: `pipeline/utils/cefr.py` (new file)

### Why it was created

Mismatch 3 required the field editor to apply the same CEFR mapping the GIZ
renderer uses.  The mapping table (`_CEFR_MAP`, `_map_cefr`) was previously
defined locally inside `templates/giz.py` only.

Duplicating it in `field_editor.py` would create a silent divergence risk — if
the GIZ team ever adds a new level (e.g. `"advanced"`) to the renderer's map,
the field editor would silently not know about it and send Claude the wrong
context.

### Decision

Extract to `pipeline/utils/cefr.py` as the single source of truth.  Both
`templates/giz.py` and `pipeline/agents/field_editor.py` import from here.
A `pipeline/utils/__init__.py` was also created to make the directory a package.

### Public API

```python
# pipeline/utils/cefr.py
CEFR_MAP: dict[str, str]   # full mapping table
map_cefr(level: str) -> str  # returns mapped label or level unchanged
```

### How `templates/giz.py` was updated

The old local definitions were replaced with a single import line.  The private
aliases `_CEFR_MAP` and `_map_cefr` are preserved so internal call sites in
`giz.py` (`_resolve_cefr`) require no further changes:

```python
from pipeline.utils.cefr import CEFR_MAP as _CEFR_MAP, map_cefr as _map_cefr  # noqa: E402
```

---

## Fix 1 — GIZ Key Qualifications priority inversion

### Files changed
- `pipeline/agents/field_editor.py`
- `cv-drafter-ui/src/lib/utils/locatorToDotPath.ts`
- `cv-drafter-ui/src/components/DocxViewer.tsx`

### Root cause

The GIZ renderer (`templates/giz.py → _build_context`) prefers
`generated_fields[j].content` (where `field_key == "key_qualifications"` and
content is non-empty) over the raw `key_qualifications` array.

Before this fix, both the frontend and backend used the opposite priority —
checking the raw array first.  This produced two failure modes once Agent 4
generates non-empty KQ content:

- **Failure A (skip):** The docx displays generated text; the user clicks it;
  the frontend matches against the raw list (different text); match score falls
  below threshold; path falls back to `paragraph_N`; backend also matches
  against raw list; stays `paragraph_N`; `get_by_path` raises `KeyError`.
  Edit lands in `skipped`.

- **Failure B (silent no-op):** If texts partially overlap enough to match, the
  path resolves to `key_qualifications[i]`.  The field editor writes there.  On
  the next render, `_build_context` finds non-empty `generated_fields` entries
  and ignores `key_qualifications` entirely.  The docx is unchanged.

### Backend changes (`field_editor.py`)

**`_key_qualification_bullets`** — priority reversed:

```python
def _key_qualification_bullets(generated: dict) -> list[str]:
    # 1. generated_fields content (non-empty) — matches renderer priority
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
    # 2. raw key_qualifications list as fallback
    raw = generated.get("key_qualifications")
    if isinstance(raw, list) and raw:
        out = [str(x).strip() for x in raw if str(x).strip()]
        if out:
            return out
    return []
```

**Two new helpers** were added to support Fix 1+ (see below):

```python
def _key_qualification_source(generated: dict) -> str:
    """Returns "generated_fields", "raw", or "none"."""

def _key_qualification_path_for_index(generated: dict, bullet_index: int) -> str:
    """
    Returns generated_fields[j].content when GF is the active source,
    or key_qualifications[bullet_index] when the raw list is the fallback.
    """
```

**`resolve_paragraph_placeholder_path`** — after matching a bullet index, now
calls `_key_qualification_path_for_index` instead of hard-coding
`key_qualifications[{idx}]`.  This closes the silent-no-op gap for
`paragraph_N` fallback paths:

```python
idx = _match_key_qualification_index(a, bullets)
if idx is not None:
    return _key_qualification_path_for_index(generated, idx)
    # was: return f"key_qualifications[{idx}]"
```

### Frontend changes (`locatorToDotPath.ts`)

**`effectiveKeyQualifications`** — priority reversed to match renderer:

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

**New export `resolveKeyQualificationsPath`** — parallel to the existing
`resolveTasksAssignedPath`, finds the `generated_fields[j].content` path for
bullet at `bulletIndex`.  Returns `null` when the raw list is the active source
(caller falls back to `key_qualifications[bulletIndex]`):

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
  if (kqEntries.length === 0) return null;
  if (bulletIndex >= kqEntries.length) return null;
  const j = generatedFields.indexOf(kqEntries[bulletIndex]);
  if (j === -1) return null;
  return `generated_fields[${j}].content`;
}
```

**`LocatorToDotPathOptions`** — extended with an optional `cvData` field so
`locatorToDotPath` can determine the active KQ source at path-generation time:

```typescript
export type LocatorToDotPathOptions = {
  keyQualifications?: string[];
  docBlocks?: KqDocBlock[];
  otherRelevantInfo?: string;
  cvData?: CVDataLite;   // ← added
};
```

**Paragraph branch of `locatorToDotPath`** — after `matchKeyQualificationIndex`
returns a match, tries `resolveKeyQualificationsPath` first; only falls back to
`key_qualifications[kqIdx]` if that returns `null` (i.e. raw list is active):

```typescript
if (kqIdx !== null) {
  const kqPath =
    resolveKeyQualificationsPath(options?.cvData?.generated_fields, kqIdx) ??
    `key_qualifications[${kqIdx}]`;
  return { kind: "simple", dotPath: kqPath, confidence: "mapped", ... };
}
```

### `DocxViewer.tsx` change

The `locatorDotPathOptions` memo now passes `cvData` into the options object so
`locatorToDotPath` has what it needs:

```typescript
if (cvData) opts.cvData = cvData;
```

No other changes to `DocxViewer.tsx`.

---

## Fix 2 — WB Employment Record wrong field names

### File changed
- `cv-drafter-ui/src/lib/utils/locatorToDotPath.ts`

### Root cause

`wbTableToDotPath` (case 2, Employment Record) was emitting:
- Cell 0: `employment_record[i].period` — this field does not exist in
  `EmploymentRecord`.  The renderer computes `period` at render time from
  `from_date` + `to_date`; writing directly to `period` in `generated` is a
  100% skip (path resolution failure) because `get_by_path` raises `KeyError`.
- Cell 1 (Position option): `employment_record[i].position` — the model field
  is `positions_held`.  Same 100% skip rate.

### Fix

Cell 0 changed from a `simple` path to a `composite` with the two raw date
fields:

```typescript
if (cellIndex === 0)
  return {
    kind: "composite", dotPath: "", confidence: "mapped",
    label: `Employment ${i + 1} — period`,
    options: [
      { label: "From", dotPath: `employment_record[${i}].from_date` },
      { label: "To",   dotPath: `employment_record[${i}].to_date`   },
    ],
  };
```

Cell 1 Position option corrected:

```typescript
{ label: "Position", dotPath: `employment_record[${i}].positions_held` }
// was: `employment_record[${i}].position`
```

No backend changes required — `from_date`, `to_date`, and `positions_held` all
exist in the `EmploymentRecord` Pydantic model and are handled by the existing
`get_by_path` / `set_by_path` machinery.

---

## Fix 3 — GIZ Languages CEFR blind spot

### File changed
- `pipeline/agents/field_editor.py`

### Root cause

The GIZ renderer applies `_resolve_cefr` at render time: if `reading_cefr` is
empty it maps `reading_raw` to a CEFR label and displays that.  The field editor
receives `current_value = ""` (the raw stored value of `reading_cefr`) while the
user sees e.g. "C2" (the mapped `reading_raw` value) in the document.

The edit still lands in `applied` — writing to `reading_cefr` is correct and the
next render uses it.  But Claude edits blind: its `current_value` block says `""`
while the user's instruction references the displayed value.

### Decision: Option A (agent sees the displayed value)

In `run_field_editor`, between `get_by_path` and `call_claude`, check whether
enrichment is needed and substitute `prompt_current_value`:

```python
prompt_current_value = current_value
if donor == "giz" and not str(current_value).strip():
    _cefr_m = re.match(
        r"^languages\[(\d+)\]\.(reading|speaking|writing)_cefr$", field_path
    )
    if _cefr_m:
        _lang_idx = int(_cefr_m.group(1))
        _raw_key = f"{_cefr_m.group(2)}_raw"
        try:
            _raw_val = mutated.get("languages", [])[_lang_idx].get(_raw_key, "")
            _mapped = _map_cefr(str(_raw_val))
            if _mapped:
                prompt_current_value = _mapped
        except (IndexError, AttributeError, TypeError):
            pass  # enrichment is advisory — failure is silent
```

`call_claude` receives `prompt_current_value`; `set_by_path` still writes the
agent's result to the original `cefr` path; `reading_raw` is left unchanged.

The `_normalized_scalar_equals` unchanged-value guard compares against the
original `current_value` (the empty string), not `prompt_current_value`, so a
fresh agent response (e.g. `"B2"`) correctly passes the guard.

---

## Fix 5 — WB Detailed Tasks index misalignment

### File changed
- `templates/wb.py`

### Root cause

The renderer filtered `generated_fields` to only non-empty `detailed_tasks`
entries before building the `detailed_tasks` list:

```python
# Before fix — non-empty filter present
detailed_tasks = [
    gf.get("content", "").strip()
    for gf in cv.get("generated_fields", [])
    if gf.get("field_key") == "detailed_tasks" and gf.get("content", "").strip()
]
```

The frontend's `resolveTasksAssignedPath` filters on `field_key` only (no
content check).  When any `detailed_tasks` entry has empty content, the two
lists have different lengths and every index from that point onwards is
misaligned — edits apply to the correct `generated_fields[j]` slot but render
under the wrong project.

### Fix

Remove the non-empty content filter:

```python
# After fix — unfiltered, matching frontend behaviour
detailed_tasks = [
    gf.get("content", "").strip()
    for gf in cv.get("generated_fields", [])
    if gf.get("field_key") == "detailed_tasks"
]
```

Empty entries now render as empty cells in the docx, which is the correct
behaviour — it signals that no task was generated for that project and makes the
cell available for a field edit.

No changes needed in `locatorToDotPath.ts` or `field_editor.py`.

---

## Fix 6 — WB Renderer missing context keys

### File changed
- `templates/wb.py`

### Root cause

The WB template references `{{ employer }}`,
`{{ membership_professional_bodies }}`, `{{ countries_display }}`, and
`{{ other_skills_display }}`, but `_build_context` did not include any of these
keys in its return dict.  Field editor writes to `employer` and
`membership_professional_bodies` were therefore silent no-ops — the edit was
stored in `generated_fields.json` and reported as `applied`, but at render time
`_build_context` produced an empty string for those template variables regardless
of what was written.

### Fix

Added the missing keys to the `_build_context` return dict:

```python
# Computed display strings
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

`countries_display` and `other_skills_display` are computed display strings with
no direct CVData path; the frontend correctly does not generate editable paths
for them.  They are added here so the template cells are populated on render.

---

## Tests added

### `tests/test_field_editor_skip_reasons.py`

New imports:
```python
from pipeline.agents.field_editor import (
    _key_qualification_bullets,
    _key_qualification_source,
    _key_qualification_path_for_index,
    ...
)
```

New test classes:

| Class | What it tests |
|-------|---------------|
| `TestKeyQualificationBulletsReversedPriority` | GF preferred; raw fallback; empty GF content falls through; both-empty returns `[]`; empty entries filtered from GF list |
| `TestKeyQualificationSource` | Returns `"generated_fields"`, `"raw"`, or `"none"` correctly |
| `TestKeyQualificationPathForIndex` | Returns `generated_fields[j].content` when GF active; `key_qualifications[i]` when raw active; handles non-zero `j` (entries before KQ in GF array) |
| `TestParagraphPlaceholderResolutionWithGeneratedFields` | `paragraph_N` resolves to `generated_fields[j].content` when GF is active; resolves to `key_qualifications[i]` when GF content is empty |

### `tests/test_field_editor_context.py`

New test class:

| Class | What it tests |
|-------|---------------|
| `TestCefrEnrichment` | Enriched `current_value` ("fluent" → "C2") passed to Claude; write targets cefr field not raw; no enrichment when cefr already set; no enrichment when donor ≠ "giz"; all three CEFR field types enriched |

**Total: 70 tests, all passing.**

---

## Verification

```
# Backend (cv_pipeline conda env)
pytest tests/test_field_editor_skip_reasons.py tests/test_field_editor_context.py -v
# → 70 passed in 0.83s

# Frontend
npx tsc --noEmit   (in cv-drafter-ui/)
# → no output (clean)
```

---

## Files modified summary

| File | Nature of change |
|------|-----------------|
| `pipeline/utils/__init__.py` | New (empty package marker) |
| `pipeline/utils/cefr.py` | New — shared CEFR map and `map_cefr()` |
| `templates/giz.py` | Replace local CEFR definitions with import from `pipeline.utils.cefr` |
| `templates/wb.py` | Fix 5: remove non-empty filter; Fix 6: add 4 missing context keys |
| `pipeline/agents/field_editor.py` | Fix 1: reverse KQ priority + new helpers + resolver update; Fix 3: CEFR enrichment |
| `src/lib/utils/locatorToDotPath.ts` | Fix 1: reverse `effectiveKeyQualifications`, add `resolveKeyQualificationsPath`, update paragraph branch; Fix 2: employment cell 0/1 corrected |
| `src/components/DocxViewer.tsx` | Pass `cvData` into `locatorDotPathOptions` memo |
| `tests/test_field_editor_skip_reasons.py` | 13 new test cases for Fix 1 |
| `tests/test_field_editor_context.py` | 5 new test cases for Fix 3 |
