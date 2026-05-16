# Frontend Context — Field Edit Skip Reasons

**Audience**: Frontend team.
**Scope**: Breaking change to the `POST /sessions/{id}/field-edit` response
shape. No other endpoints are affected.

---

## What changed and why

Previously, when the field editor agent could not apply an edit, the field
path was silently added to a `skipped` array of plain strings. The frontend
had no way to tell the user why the edit was rejected, making it impossible
to rephrase the instruction and try again.

The `skipped` array now contains **objects** with a `path` and a `reason`
key. The reason is a human-readable explanation, capped at 200 characters
with a trailing `…` if truncated.

---

## Response shape — before vs. after

### Before (old — no longer valid)

```json
{
  "session_id": "...",
  "status": "checkpoint_3_pending",
  "round": 2,
  "applied": ["relevant_projects[1].location"],
  "skipped": ["key_qualifications[2]"],
  "message": "..."
}
```

### After (new — current)

```json
{
  "session_id": "...",
  "status": "checkpoint_3_pending",
  "round": 2,
  "applied": ["relevant_projects[1].location"],
  "skipped": [
    {
      "path": "key_qualifications[2]",
      "reason": "Instruction requires adding a certification not present in the original value."
    }
  ],
  "message": "..."
}
```

---

## Required frontend changes

### 1. Update any code that reads `skipped` elements as strings

```typescript
// BEFORE — broken after this change
skipped.forEach((path: string) => {
  showWarning(`Edit skipped: ${path}`);
});

// AFTER
skipped.forEach((item: { path: string; reason: string }) => {
  showWarning(`Edit skipped for "${item.path}": ${item.reason}`);
});
```

### 2. Display the reason inline

Wherever a skipped edit is surfaced (warning banner, inline annotation on
the field, toast notification), show the `reason` directly beneath or
alongside the field path. This allows the user to rephrase their instruction
without leaving the UI.

Recommended display pattern:

```
⚠ "key_qualifications[2]" was not applied.
  Reason: Instruction requires adding a certification not present in the original value.
  → Try rephrasing the instruction using only information visible in the field.
```

### 3. Update TypeScript types

If you maintain typed API response models, update the `FieldEditResponse`
type:

```typescript
// BEFORE
interface FieldEditResponse {
  session_id: string;
  status: string;
  round: number;
  applied: string[];
  skipped: string[];          // <-- old
  message: string;
}

// AFTER
interface FieldEditSkip {
  path: string;
  reason: string;             // max 200 chars; may end with "…" if truncated
}

type KqSource = "ai_generated" | "extracted" | "absent";

interface FieldEditResponse {
  session_id: string;
  status: string;
  round: number;
  applied: string[];
  skipped: FieldEditSkip[];   // <-- updated (was string[])
  message: string;
  kq_source: KqSource;        // <-- new (Round 2)
}
```

### `kq_source` usage guidance

`kq_source` indicates which data source provided the key qualification bullets at the time edits were submitted. It reflects the **post-edit** state.

| Value | Meaning | Recommended UI action |
|-------|---------|----------------------|
| `"ai_generated"` | Agent 4's ToR-tailored bullets are active. Edits targeted `generated_fields[j].content` paths. | Normal flow — no warning needed. |
| `"extracted"` | Agent 4 produced no usable content. Edits targeted Agent 1's raw `key_qualifications[i]` list. | **Display a contextual warning banner** so the user knows they are editing raw CV extraction, not AI-generated content. E.g. _"Note: AI content generation failed. You are editing the raw extracted text."_ |
| `"absent"` | Neither source has any bullets. | The key qualifications section is empty; KQ edits are unlikely to have any effect. |

---

## Reason contract

| Property | Value |
|----------|-------|
| Max length | 200 characters |
| Truncation indicator | Trailing `…` (U+2026 HORIZONTAL ELLIPSIS) |
| Encoding | UTF-8, plain text — no HTML or markdown |

### Reason categories

You do **not** need to switch on these categories — they are listed for
context only. Display the reason string as-is to the user.

| Category | Typical prefix |
|----------|---------------|
| Field path could not be traversed | `"path resolution failed: ..."` |
| Path resolves to a list or dict, not a scalar | `"resolved value is list, not a scalar. ..."` |
| Claude API call failed or returned bad JSON | `"API or parse error: ..."` |
| Agent chose to decline the instruction | *(LLM-supplied sentence, no fixed prefix)* |
| Value was edited but could not be written back | `"write-back failed: ..."` |

---

## The `applied` array is unchanged

`applied` remains a `list[str]` of bare field paths. Only `skipped` changed.

---

## Backend files changed (for reference)

| File | Change |
|------|--------|
| `api/models/requests.py` | Added `FieldEditSkip` Pydantic model; `FieldEditResponse.skipped` changed from `list[str]` to `list[FieldEditSkip]` |
| `pipeline/agents/field_editor.py` | All 5 skip paths now emit `{"path": ..., "reason": ...}` dicts; reasons truncated to 200 chars |
| `pipeline/orchestrator.py` | Return-type annotation updated (passthrough only) |
| `markdowns/API.md` | Example response and field description updated; breaking-change callout added |
