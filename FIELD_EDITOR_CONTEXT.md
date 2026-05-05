# Field Editor Agent — Context & Implementation Reference

Single reference for the `field_editor` agent: its position in the pipeline,
inputs, outputs, behaviour contract, and integration points with the orchestrator.

---

## 1. Purpose

`field_editor` is a Claude-backed agent that applies targeted, user-directed
natural language edits to specific fields in `generated_fields.json["generated"]`
before the compressor runs. It bridges the human review step (where the user
inspects a rendered preview of the CV and identifies fields to change) with the
automated compressor and final renderer.

---

## 2. Position in the pipeline

```
fields_generator
      ↓
content_reviewer          ← flags high/low severity issues; always completes
      ↓
[preview render]          ← renderer called here for the FIRST time (preview only)
      ↓                      writes runs/{session_id}/preview.docx
      ↓                      NOT uploaded to Supabase Storage
      ↓                      NOT recorded on the sessions DB row
field_editor              ← NEW agent (this document)
      ↓
compressor
      ↓
checkpoint_3
      ↓
[final render]            ← renderer called here for the SECOND time (production)
      ↓                      writes runs/{session_id}/output.docx
      ↓                      uploaded to Supabase Storage
      ↓                      output_storage_key saved to sessions DB row
completed
```

**Manifest step name**: `field_editor`

**Position in `STEP_ORDER`** ([`pipeline/manifest.py`](pipeline/manifest.py)):
Insert between `content_reviewer` and `compressor`:

```python
STEP_ORDER = [
    "cv_extractor",
    "tor_summarizer",
    "checkpoint_1",
    "cv_tor_mapper",
    "checkpoint_2",
    "fields_generator",
    "content_reviewer",
    "field_editor",      # ← inserted here
    "compressor",
    "checkpoint_3",
    "renderer",
]
```

---

## 3. Preview render

The renderer is called **twice** per session:

| Call | When | Output file | Uploaded to Storage | DB row updated |
|------|------|-------------|---------------------|----------------|
| Preview | After `content_reviewer` completes, before `field_editor` | `runs/{session_id}/preview.docx` | ❌ No | ❌ No |
| Final | After `checkpoint_3` approved (`run_phase4`) | `runs/{session_id}/output.docx` | ✅ Yes | ✅ Yes |

The preview render uses the same renderer (`get_renderer(target_format)`) and the
same `generated_fields.json["generated"]` snapshot that `content_reviewer` just
finished with. It passes an explicit `output_path` override so the renderer writes
`preview.docx` instead of `output.docx`.

`preview.docx` is ephemeral: it lives only in the local run directory. It is
served to the frontend via a new local file endpoint or a temporary signed URL
generated from the local path — **not** via the existing `output_storage_key`
download route (that route is reserved for the final production output).

The orchestrator calls the preview render inline (not as a background task) at
the end of `run_phase3`, immediately after `content_reviewer` finishes and before
setting the DB status to `field_editor_pending`.

---

## 4. DB status

A new status value is required:

```
field_editor_pending
```

This is the pause point between the preview render and the user submitting their
edit batch. The orchestrator sets this status after the preview render completes.
The pipeline resumes when the user submits a batch via `POST /sessions/{id}/field-edit`.

Add `field_editor_pending` to `SessionStatus` in
[`api/models/requests.py`](api/models/requests.py) and to
[`reset_stale_processing_sessions`](api/services/database.py) so that sessions
stuck in this state on app restart are marked `failed`.

The status machine addition:

```
processing (Phase 3)
  ↓
content_reviewer completes
  ↓
preview render → preview.docx (local only)
  ↓
field_editor_pending          ← NEW: UI shows preview + reviewer report
  ↓ (POST /sessions/{id}/field-edit)
processing
  ↓
field_editor runs
  ↓
compressor runs
  ↓
checkpoint_3_pending
```

---

## 5. HTTP endpoint

```
POST /sessions/{session_id}/field-edit
```

**Preconditions**:
- Session status must be `field_editor_pending`

**Request body**:
```json
{
  "edits": [
    {
      "field_path": "key_qualifications[2]",
      "instruction": "Make this more concise and remove the passive voice"
    },
    {
      "field_path": "relevant_projects[1].location",
      "instruction": "Change to Nairobi, Kenya"
    }
  ]
}
```

**Fields**:
- `edits` *(required, array)*: 1–5 edit objects. Validated server-side; reject
  with `422` if empty or more than 5 items.
- `edits[].field_path` *(required, string)*: Dot-path relative to
  `generated_fields["generated"]`. Numeric bracket notation (`[N]`) is equivalent
  to the dot notation used in `dot_path.py` (`key_qualifications.2`). The server
  normalises both forms before passing to the agent.
- `edits[].instruction` *(required, string)*: Natural language instruction for
  the LLM. Min 1 character.

**Response** (200):
```json
{
  "session_id": "20260425_143022_a1b2",
  "status": "processing",
  "applied": ["key_qualifications[2]", "relevant_projects[1].location"],
  "skipped": [],
  "message": "Field edits applied. Compressor starting."
}
```

**`skipped`**: Paths that could not be resolved or where the agent failed to
produce a valid replacement. These are returned to the UI for display; the
pipeline continues without those edits.

**Errors**:
- `409`: Session not in `field_editor_pending` state
- `422`: `edits` array empty or exceeds 5 items, or individual field validation fails

---

## 6. Agent inputs

The agent receives the following at runtime (assembled by the orchestrator before
calling `field_editor.run`):

| Input | Source | Description |
|-------|--------|-------------|
| `run_dir` | orchestrator | `runs/{session_id}/` path |
| `edits` | HTTP request body | List of `{field_path, instruction}` dicts, max 5 |
| `generated` | `generated_fields.json["generated"]` | Full current CVData snapshot — read at agent call time |
| `review` | `generated_fields.json["review"]` | Reviewer's report (high/low severity issues); passed as context so the agent is aware of flagged problems while editing |

The agent does **not** receive `tor_data.json`, `manifest.json`, or `mapped_cv.json`.
It operates only on the current state of `generated_fields["generated"]`.

---

## 7. Agent behaviour

### 7.1 Per-edit LLM call

The agent processes each edit in the batch **sequentially**, one LLM call per edit.
This ensures each subsequent edit operates on the already-patched state of `generated`
(important when two edits touch related fields).

For each edit:

1. Resolve `field_path` to the current value using `get_by_dot_path(generated, path)`.
2. If the path cannot be resolved → add to `skipped` list, continue to next edit.
3. Build a focused prompt (see §7.2).
4. Call Claude. Extract the new string value from the response.
5. If the response is empty or the agent signals it cannot apply the change →
   add to `skipped` list, continue.
6. Write the new value back: `set_by_dot_path(generated, path, new_value)`.
7. Add to `applied` list.

After all edits are processed, write the mutated `generated` back to
`generated_fields.json` (full file rewrite, preserving `review`, `compression`,
`generation_warnings`, and `approved` keys).

### 7.2 Prompt design

Each LLM call receives a minimal, focused prompt:

```
You are editing one field of a professional CV formatted for international 
development donors.

Current field path: {field_path}
Current value:
"""
{current_value}
"""

User instruction: {instruction}

Rules:
- Return ONLY the new field value as a plain string. No explanation, no JSON 
  wrapper, no markdown.
- Preserve the factual content of the original unless the instruction explicitly 
  asks you to change facts.
- Do not introduce claims that are not present in the original text.
- If the instruction cannot be applied without fabricating information, return 
  the original value unchanged and prefix your response with SKIP: followed by 
  a brief reason.

New value:
```

The agent checks if the response starts with `SKIP:` — if so, adds the path to
`skipped` and uses the original value (no write occurs for that field).

### 7.3 Skipped edits

A field edit is skipped (path added to `skipped`, no write) when:

- `field_path` cannot be resolved in current `generated` (path does not exist)
- The LLM returns a `SKIP:` prefixed response
- The LLM call raises an exception (agent logs the error, continues to next edit)

Skipped edits do **not** halt the pipeline. The orchestrator proceeds to the
compressor after `field_editor` completes regardless of how many edits were
skipped, as long as the agent step itself did not raise an unhandled exception.

---

## 8. Output and file writes

`field_editor` writes **only** to `generated_fields.json`.

**Write contract**: Read the full file → mutate `generated` in memory →
write the full file back. Preserve all top-level keys:

```python
data = read_json(run_dir / "generated_fields.json")
data["generated"] = mutated_generated   # only this key changes
write_json(run_dir / "generated_fields.json", data)
```

The agent does **not** write a separate output file. It does not touch
`manifest.json` directly (the orchestrator handles step status updates).

---

## 9. Manifest integration

The orchestrator updates the `field_editor` manifest step using the existing
`update_step` pattern:

```python
update_step(run_dir, "field_editor", "running")
result = await field_editor.run(run_dir, edits)
update_step(run_dir, "field_editor", "done")   # or "failed" on unhandled exception
```

The `result` dict contains `applied` and `skipped` lists, which the HTTP
response returns to the client. These are not persisted in `manifest.json` —
they are returned in the HTTP response only.

---

## 10. Iteration design (current scope vs. future)

**Current scope (single batch)**: The user submits one batch of up to 5 edits.
`field_editor` runs once, then hands off to compressor. There is no loop in the
current implementation — `field_editor_pending` is entered once and exited once.

**Future scope (iterative batches)**: The architecture is designed to support
multiple batch rounds without structural changes:

- After `field_editor` completes, instead of immediately running the compressor,
  the orchestrator could re-render a new `preview.docx` and return to
  `field_editor_pending`, allowing the user to submit another batch.
- The number of allowed iterations would be controlled by a counter (e.g.
  `manifest.params.field_editor_rounds`) that the orchestrator checks before
  deciding whether to loop back or proceed to compressor.
- The HTTP endpoint and agent code require no changes for this — only the
  orchestrator phase logic needs the loop condition.

To keep the current implementation compatible with this future extension:
- Do not hardcode "proceed to compressor" inside `field_editor.run` itself.
  The agent only edits and returns. The orchestrator decides what runs next.
- The endpoint handler checks the iteration counter (currently always 0,
  threshold currently always 1) and either re-enters `field_editor_pending`
  or proceeds to compressor.

---

## 11. Relation to existing resolve workflow

`field_editor` and `POST /sessions/{id}/resolve` are **distinct** and serve
different pipeline positions:

| | `field_editor` | `/resolve` |
|---|---|---|
| When | Before compressor, during normal flow | After `reviewer_blocked`, resuming a halted pipeline |
| Trigger | User-submitted field edits via UI | Human override of high-severity reviewer flags |
| LLM-mediated | ✅ Yes — instruction → new value | ❌ No — caller provides the new value directly |
| Runs next | Compressor (via orchestrator) | Compressor (via `run_phase3_resume`) |
| Session status entry | `field_editor_pending` | `reviewer_blocked` |

The two workflows are independent. A session goes through `field_editor_pending`
regardless of whether the reviewer flagged issues. If the reviewer blocked the
session in the old flow, that path is superseded — `field_editor_pending` now
serves as the single human intervention point before the compressor in Phase 3.

> **Migration note**: If `reviewer_blocked` as a separate halt is retained
> alongside `field_editor_pending`, clarify in the orchestrator which state takes
> precedence. The simplest approach: reviewer output is surfaced in the UI during
> `field_editor_pending` (as context alongside the preview), and `reviewer_blocked`
> as a distinct DB status is deprecated in favour of the unified pause point.

---

## 12. Files touched by this addition

| File | Change |
|------|--------|
| `pipeline/agents/field_editor.py` | New agent module |
| `pipeline/manifest.py` | Add `field_editor` to `STEP_ORDER` |
| `pipeline/orchestrator.py` | Preview render call after `content_reviewer`; `field_editor` step in `run_phase3`; `field_editor_pending` DB status set; `run_phase3_resume` entry point for batch submission |
| `api/models/requests.py` | Add `field_editor_pending` to `SessionStatus` enum; add `FieldEditRequest` model |
| `api/routers/sessions.py` | New `POST /sessions/{id}/field-edit` route |
| `api/services/database.py` | Add `field_editor_pending` to `reset_stale_processing_sessions` |
| `pipeline/paths.py` | Add `PREVIEW_DOCX` path constant (`runs/{session_id}/preview.docx`) |
| `templates/giz.py` / `templates/wb.py` | Accept optional `output_path` parameter so the preview render can write to `preview.docx` instead of `output.docx` |
