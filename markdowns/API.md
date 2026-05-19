# CV Reformatter Backend API Documentation

## Overview

The CV Reformatter API processes CVs through a 7-agent AI pipeline, producing formatted Word documents tailored for international development donors (GIZ, World Bank). The pipeline includes human approval checkpoints and a post-completion field editing workflow.

**Base URL**: `http://127.0.0.1:8000`  
**Authentication**: Supabase JWT bearer token (required for all endpoints except `/health`)

---

## Dependencies

**Python:** 3.12.13 (see `.python-version`)

Install from the compiled lockfile so local and production use the same package versions:

```bash
cd cv-drafter
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt   # optional: pytest, ruff
```

| Package | Version |
|---------|---------|
| fastapi | 0.115.12 |
| pydantic | 2.12.5 |
| pydantic-settings | 2.13.1 |
| uvicorn | 0.41.0 |
| starlette | 0.46.2 |
| supabase | 2.28.3 |
| anthropic | 0.103.1 |

Full transitive pins are in `requirements.txt` (generated from `requirements.in` via `pip-compile`).  
To update dependencies: edit `pyproject.toml` and `requirements.in`, then run `scripts/lock-deps.ps1` (Windows) or `scripts/lock-deps.sh` (macOS/Linux), and commit both input and lock files.

**Production (Railway):** `pip install -r requirements.txt` (see `railway.toml`). Redeploy with a cleared build cache after dependency changes.

---

## Quick Start

### 1. Run the Server
```bash
cd cv-drafter
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
uvicorn api.server:app --reload --host 127.0.0.1 --port 8000
```

### 2. Health Check
```bash
curl http://127.0.0.1:8000/health
```

---

## Authentication

All endpoints (except `/health`) require a Supabase JWT bearer token in the `Authorization` header:

```bash
curl -H "Authorization: Bearer <SUPABASE_JWT_TOKEN>" http://127.0.0.1:8000/sessions
```

---

## Endpoints

### Health & Status

#### `GET /health`
Check server liveness.

**Response** (200):
```json
{
  "status": "ok"
}
```

---

### Session Management

#### `POST /sessions`
Create a new CV reformatting session.

**Request Body** (application/json):
```json
{
  "target_format": "giz",
  "source_filename": "cv.docx",
  "tor_filename": "tor.pdf",
  "proposed_position": "Senior Water Engineer",
  "category": "Senior Expert",
  "employer": "ABC Consulting",
  "years_with_firm": "5",
  "page_limit": 4,
  "job_description": "Lead water infrastructure projects",
  "recruiter_comments": "Initial submission"
}
```

**Parameters**:
- `target_format` *(required, enum)*: `"giz"` or `"world_bank"`. World Bank rendering requires `templates/WB-Template.docx` at runtime (same pattern as GIZ).
- `source_filename` *(required, string)*: Name of the CV file (e.g., `"cv.docx"`, `"cv.pdf"`)
- `tor_filename` *(optional, string)*: Name of the Terms of Reference file
- `proposed_position` *(optional, string)*: Position title for the formatted CV
- `category` *(optional, string)*: Expert category (e.g., "Senior Expert", "Junior Expert")
- `employer` *(optional, string)*: Consulting firm or employer name
- `years_with_firm` *(optional, string)*: Years at firm (e.g., "5", "5+", "<1")
- `page_limit` *(optional, integer)*: Max output pages (1–100; default 4 for GIZ)
- `job_description` *(optional, string)*: Free-text job description
- `recruiter_comments` *(optional, string)*: Initial recruiter feedback

**Compression parameters (pipeline-internal)**

The interactive OpenAPI docs may still list `target_words` and `compression_ratio` on this request body. **Client applications should omit them.** End users do not configure or display compressor limits in normal flows—the pipeline resolves them from **donor defaults** (`FORMAT_PROFILES` for the chosen `target_format`) plus fixed server fallbacks when Phase 1 writes `runs/{session_id}/manifest.json` (`params`). As of the current handler, **`POST /sessions` does not persist those two fields onto the Supabase session row**, so sending them in the JSON body **has no effect** on a run **unless** the server is updated to persist them on the session row.

For the full mechanic, see [`PIPELINE_CONTEXT.md`](PIPELINE_CONTEXT.md) §§1, 4, and 9.

**Response** (201):
```json
{
  "session_id": "20260425_143022_a1b2",
  "status": "queued"
}
```

**Errors**:
- `429`: Max 3 concurrent active sessions per user
- `422`: Invalid request body

---

#### `GET /sessions/{session_id}/status`
Get current session status, file keys, and download URLs.

**Response** (200):
```json
{
  "session_id": "20260425_143022_a1b2",
  "user_id": "user-uuid",
  "status": "checkpoint_1_pending",
  "target_format": "giz",
  "round": 1,
  "source_filename": "cv.docx",
  "tor_filename": "tor.pdf",
  "source_storage_key": "20260425_143022_a1b2/source/cv.docx",
  "tor_storage_key": "20260425_143022_a1b2/tor/tor.pdf",
  "output_storage_key": null,
  "page_limit": 4,
  "job_description": "Lead water infrastructure projects",
  "recruiter_comments": "Initial submission",
  "error_message": null,
  "download_url": null,
  "created_at": "2026-04-25T14:30:22.123456Z",
  "updated_at": "2026-04-25T14:30:22.123456Z"
}
```

**Status Values**:
- `queued` — Waiting for files and `POST /start`
- `processing` — Pipeline is running
- `checkpoint_1_pending` — Agents 1 & 2 done, awaiting approval
- `checkpoint_2_pending` — Agent 3 done, awaiting approval
- `checkpoint_3_pending` — Agents 4, 5, 6 done (or field edits applied), awaiting approval before re-render
- `reviewer_blocked` — Content reviewer flagged high-severity issues during pipeline run
- `completed` — Rendering done, output ready for download
- `failed` — Pipeline error (see `error_message`)

---

### File Upload

#### `POST /sessions/{session_id}/upload/source`
Upload the source CV file (.docx or .pdf).

**Form Data**:
- `file` *(required, file)*: CV file (max size: check backend config)

**Query Parameters**:
- `expires_seconds` *(optional, integer)*: Signed URL expiration time (60–604800 seconds; default 3600)

**Response** (201):
```json
{
  "storage_key": "20260425_143022_a1b2/source/cv.docx",
  "signed_url": "https://...(signed URL)...",
  "expires_in": 3600
}
```

**Example**:
```bash
curl -X POST \
  -H "Authorization: Bearer <TOKEN>" \
  -F "file=@cv.docx" \
  http://127.0.0.1:8000/sessions/{session_id}/upload/source
```

---

#### `POST /sessions/{session_id}/upload/tor`
Upload the Terms of Reference file (optional, .docx or .pdf).

**Form Data**:
- `file` *(required, file)*: ToR file

**Query Parameters**:
- `expires_seconds` *(optional, integer)*: Signed URL expiration time (default 3600)

**Response** (201):
```json
{
  "storage_key": "20260425_143022_a1b2/tor/tor.pdf",
  "signed_url": "https://...",
  "expires_in": 3600
}
```

---

### Signed Download URLs

#### `GET /sessions/{session_id}/files/source/download-url`
Get a fresh signed URL for the source CV.

**Query Parameters**:
- `expires_seconds` *(optional, integer)*: Expiration time (60–604800; default 3600)

**Response** (200):
```json
{
  "signed_url": "https://...",
  "expires_in": 3600
}
```

---

#### `GET /sessions/{session_id}/files/tor/download-url`
Get a fresh signed URL for the ToR file.

**Response** (200):
```json
{
  "signed_url": "https://...",
  "expires_in": 3600
}
```

---

#### `GET /sessions/{session_id}/files/output/download-url`
Get a fresh signed URL for the output Word document (only after completion).

**Response** (200):
```json
{
  "signed_url": "https://...",
  "expires_in": 3600
}
```

---

### Pipeline Execution

#### `POST /sessions/{session_id}/start`
Begin processing (runs Phase 1: parallel CV + ToR extraction).

**Preconditions**:
- Session status must be `queued`
- Source CV must be uploaded

**Response** (200):
```json
{
  "session_id": "20260425_143022_a1b2",
  "status": "processing",
  "message": "Processing started in the background"
}
```

---

#### `GET /sessions/{session_id}/manifest`
Poll the fine-grained step-by-step progress manifest.

**Response** (200):
```json
{
  "session_id": "20260425_143022_a1b2",
  "db_status": "checkpoint_1_pending",
  "checkpoint_pending": "checkpoint_1",
  "reviewer_blocked": false,
  "steps": [
    {
      "name": "cv_extractor",
      "status": "done",
      "completed_at": "2026-04-25T14:31:00.123456Z"
    },
    {
      "name": "tor_summarizer",
      "status": "done",
      "completed_at": "2026-04-25T14:31:05.123456Z"
    },
    {
      "name": "checkpoint_1",
      "status": "pending",
      "completed_at": null
    },
    {
      "name": "cv_tor_mapper",
      "status": "waiting",
      "completed_at": null
    }
  ]
}
```

**Step Statuses**:
- `waiting` — Not yet started
- `running` — Currently executing
- `done` — Completed successfully
- `pending` — Awaiting human approval (checkpoints only)
- `blocked` — Content reviewer flagged high-severity issues
- `failed` — Exception raised

---

#### `POST /sessions/{session_id}/tor/select-pool`
Persist the user-selected ToR pool index for downstream agents.

This should be called after Phase 1 (`checkpoint_1_pending`) when `tor_data.json`
contains multiple (or single) pools and before approving `checkpoint_1`.

**Request Body** (application/json):
```json
{
  "selected_pool_index": 0
}
```

**Response** (200):
```json
{
  "session_id": "20260425_143022_a1b2",
  "selected_pool_index": 0,
  "pool_count": 2,
  "position_title": "Team Leader",
  "message": "ToR pool selection saved."
}
```

**Errors**:
- `400` — invalid index or malformed `tor_data.pools`
- `404` — `tor_data.json` not available yet

---

#### `GET /sessions/{session_id}/tor/pools`
Get ToR pools and current selection for checkpoint-1 picker UIs.

**Response** (200):
```json
{
  "session_id": "20260425_143022_a1b2",
  "pools": [
    {
      "position_title": "Team Leader",
      "sector": "Water",
      "key_tasks": ["Task 1", "Task 2"]
    }
  ],
  "selected_pool_index": 0
}
```

**Errors**:
- `400` — malformed `tor_data` envelope (e.g. invalid index type/range)
- `404` — `tor_data.json` not available yet

---

#### `POST /sessions/{session_id}/approve/{checkpoint}`
Approve a checkpoint and resume the next phase.

**Parameters**:
- `checkpoint` *(required, enum)*: `checkpoint_1`, `checkpoint_2`, or `checkpoint_3`

**Checkpoint-specific preconditions**:
- `checkpoint_1`: `tor_data.json.selected_pool_index` must be set to a valid index in `tor_data.json.pools`. Otherwise approval is rejected with `409`.

**Request Body** (application/json):
```json
{
  "notes": "Looks good, proceed with mapping"
}
```

**Parameters**:
- `notes` *(optional, string)*: Human-readable approval notes

**Response** (200):
```json
{
  "session_id": "20260425_143022_a1b2",
  "approved_checkpoint": "checkpoint_1",
  "next_phase": "cv_tor_mapper",
  "status": "processing",
  "message": "checkpoint_1 approved. Next phase 'cv_tor_mapper' starting."
}
```

---

#### `GET /sessions/{session_id}/manifest`
Get detailed pipeline manifest (see above).

---

#### `GET /sessions/{session_id}/review`
Get the Content Reviewer's assessment (high/low severity issues).

**Preconditions**:
- Reviewer must have completed (status `reviewer_blocked` or after resolution)

**Response** (200):
```json
{
  "session_id": "20260425_143022_a1b2",
  "high_severity": [
    {
      "path": "generated_fields.0.content",
      "field": "Unverifiable claim",
      "issue": "'10-year track record' cannot be traced to any project in CVData",
      "recommendation": "Remove or rephrase with grounded evidence",
      "solvability": "human"
    }
  ],
  "low_severity": [
    {
      "path": "generated_fields.1.content",
      "field": "Filler language",
      "issue": "Passive language: 'was responsible for'",
      "original": "was responsible for designing the framework",
      "fixed": "Designed the framework",
      "solvability": "pipeline"
    }
  ],
  "passed": false,
  "generation_warnings": [
    "More than 1 bullet has source='tor' (weak CV grounding)"
  ]
}
```

**`solvability` values**:
- `"pipeline"` — the `field_editor` agent can resolve this by rewriting the field value (date errors, passive language, word-count overruns, etc.)
- `"human"` — requires recruiter judgement or external information (unverifiable claims, missing ToR competencies, language proficiency gaps, experience threshold failures)

---

#### `GET /sessions/{session_id}/output`
Get the final generated CV data (after all agents complete).

When a `compression` object is included, it is **output metadata** from Agent 6: `target_words` (and related fields) reflect the **effective cap the compressor applied** using internal defaults—not a request body knob clients set here.

**Response** (200):
```json
{
  "session_id": "20260425_143022_a1b2",
  "cv_data": {
    "proposed_position": "Senior Water Engineer",
    "category": "Senior Expert",
    "employer": "ABC Consulting",
    "personal_info": {
      "first_names": "John",
      "family_name": "Doe",
      "date_of_birth": "15 March 1980",
      "nationality": "USA",
      "email": "john@example.com"
    },
    "relevant_projects": [...],
    "education": [...],
    "languages": [...]
  },
  "generation_warnings": [],
  "review": { ... },
  "compression": {
    "applied": true,
    "words_before": 2500,
    "words_after": 2000,
    "target_words": 2000
  }
}
```

---

#### `GET /sessions/{session_id}/warnings`
Retrieve all pipeline warnings aggregated from every stage of the session.

These warning lists have always been written to the run-directory JSON artifacts but were
not previously transmitted to the frontend. This endpoint collects them from all four
sources and returns them in a single response. It is additive — no existing response shapes
are modified.

**Availability**: Safe to call at any point after Phase 1 completes. Returns `warnings: []`
(not `404`) when no warnings were produced. Returns partial results if some artifacts are
not yet present — each source is read independently and failures are non-fatal.

**Response** (200):
```json
{
  "session_id": "20260425_143022_a1b2",
  "warnings": [
    {
      "stage": "extraction",
      "kind": "extraction_warning",
      "message": "relevant_projects[3].project_name could not be determined from source table layout.",
      "details": null
    },
    {
      "stage": "alignment",
      "kind": "threshold_activation",
      "message": "Project 'BADGE Grid Expansion' dropped — score 0.28 below threshold 0.30.",
      "details": null
    },
    {
      "stage": "manifest",
      "kind": "scoring_keywords_empty",
      "message": "tor_summarizer: all scoring_keywords lists empty despite non-empty ToR input.",
      "details": { "tor_word_count": 142 }
    },
    {
      "stage": "generation",
      "kind": "generation_warning",
      "message": "More than 1 bullet has source='tor' (weak CV grounding).",
      "details": null
    }
  ],
  "counts": {
    "extraction": 1,
    "alignment": 1,
    "manifest": 1,
    "generation": 1
  }
}
```

**Response fields**:
- `warnings`: All warnings in pipeline stage order (extraction → alignment → manifest → generation). Empty list when all checks passed.
- `counts`: Per-stage warning counts. Keys are always present with value `0` when a stage produced no warnings.
- `warnings[].stage`: One of `"extraction"`, `"alignment"`, `"manifest"`, `"generation"`.
- `warnings[].kind`: Warning type string as written by the pipeline. See table below.
- `warnings[].message`: Human-readable warning message.
- `warnings[].details`: Optional structured dict for programmatic consumers; `null` when absent.

**Stage → source file mapping**:

| `stage` | Source file | Field read |
|---------|-------------|------------|
| `extraction` | `cv_data.json` | `data.extraction_warnings[]` |
| `alignment` | `mapped_cv.json` | `alignment.warnings[]` |
| `manifest` | `manifest.json` | `warnings[]` (structured dicts or plain strings) |
| `generation` | `generated_fields.json` | `generation_warnings[]` |

**Common `kind` values**:

| `kind` | Stage | When emitted |
|--------|-------|-------------|
| `extraction_warning` | `extraction` | Generic A1 extraction quality issue (date inversion, placeholder text, merged-cell name failure, etc.) |
| `alignment_warning` | `alignment` | Generic A3 alignment issue |
| `threshold_activation` | `alignment` | A3 dropped a project below the relevance threshold |
| `scoring_keywords_empty` | `manifest` | A2 returned empty keyword lists despite non-empty ToR |
| `position_title_empty` | `manifest` | A2 returned no position title |
| `generation_warning` | `generation` | Generic A4/A6 generation issue |
| `generation_warnings_high` | `generation` | A4 flagged a high-severity generation concern |
| `generation_warnings_low` | `generation` | A4 flagged a low-severity generation concern |

**Example**:
```bash
curl http://127.0.0.1:8000/sessions/{session_id}/warnings \
  -H "Authorization: Bearer <TOKEN>"
```

---

### Content Resolution (Reviewer Blocked)

#### `POST /sessions/{session_id}/resolve`
Resolve high-severity content issues and resume the pipeline.

**Preconditions**:
- Session status must be `reviewer_blocked`

**Request Body** (application/json):
```json
{
  "overrides": {
    "generated_fields.0.content": "Designed grid-integration framework adopted by 3 provinces"
  },
  "force_pass": false
}
```

**Parameters**:
- `overrides` *(optional, object)*: Dot-path field corrections (e.g., `"generated_fields.0.content"`)
- `force_pass` *(optional, boolean)*: If `true`, mark reviewer as passed despite flagged issues (default `false`)

**Response** (200):
```json
{
  "session_id": "20260425_143022_a1b2",
  "status": "processing",
  "message": "Review resolved. Compressor starting."
}
```

---

### Field Edit Workflow

#### `POST /sessions/{session_id}/field-edit`

> **Breaking change**: The `skipped` array now contains **objects** (`{"path": str, "reason": str}`)
> rather than plain strings. Frontend clients must be updated to read `item.path` and `item.reason`
> instead of treating each element as a bare path string.
> See `additions/FRONTEND_SKIP_REASONS_CONTEXT.md` for the full migration guide.

Apply targeted natural-language edits to specific CV fields after the pipeline
has completed. Replaces the deprecated `POST /comments` revision workflow.

The user selects fields via the DocxViewer on the frontend and provides a natural
language instruction for each. The `field_editor` agent applies each instruction
via an individual LLM call, writes the result back to
`generated_fields.json["generated"]`, then halts at `checkpoint_3_pending` for
approval before the renderer produces a new `output.docx`.

**Preconditions**:
- Session status must be `completed` or `checkpoint_3_pending`

**Request Body** (application/json):
```json
{
  "edits": [
    {
      "field_path": "key_qualifications[2]",
      "instruction": "Make this more concise and remove passive voice"
    },
    {
      "field_path": "relevant_projects[1].location",
      "instruction": "Change to Nairobi, Kenya"
    }
  ]
}
```

**Parameters**:
- `edits` *(required, array)*: 1–5 edit objects. Rejected with `422` if empty or more than 5 items.
- `edits[].field_path` *(required, string)*: Path to the target field relative to `generated_fields["generated"]`. Both bracket notation (`key_qualifications[2]`) and dot notation (`key_qualifications.2`) are accepted.
- `edits[].instruction` *(required, string)*: Natural language instruction for the LLM agent (min 1 character).

**Response** (200):
```json
{
  "session_id": "20260425_143022_a1b2",
  "status": "checkpoint_3_pending",
  "round": 2,
  "applied": ["relevant_projects[1].location"],
  "skipped": [
    {
      "path": "key_qualifications[2]",
      "reason": "Instruction requires adding a certification not present in the original value."
    }
  ],
  "kq_source": "ai_generated",
  "message": "Field edits applied. Awaiting checkpoint_3 approval before re-render."
}
```

**Response fields**:
- `applied`: Paths where the agent successfully wrote a new value
- `skipped`: Array of objects, each with `path` and `reason` keys, for edits that were not
  applied. Reason is capped at 200 characters with a trailing `…` if the source was longer.
  Reason categories: path resolution failure, non-scalar target, LLM skip decision, API error,
  write-back failure. The pipeline proceeds regardless.
- `round`: The new round number after incrementing
- `kq_source`: Which data source provided the key qualification bullets that edits targeted,
  computed from the **post-edit** state of `generated_fields.json`.
  - `"ai_generated"` — Agent 4's ToR-tailored content is active; edits targeted `generated_fields[j].content` paths.
  - `"extracted"` — Agent 4 produced no usable content; edits targeted Agent 1's raw `key_qualifications[i]` list. **Frontend should display a contextual warning** so the user knows they are editing raw extraction, not AI-generated content.
  - `"absent"` — Neither source has any bullets; the key qualifications section is empty.

**Behaviour**:
- Increments the session `round` counter immediately
- Runs `field_editor` agent sequentially across all edits (each edit operates on the already-patched state from the previous edit)
- Agent receives word-limit, donor format, and CV context to guide each edit
- Halts at `checkpoint_3_pending` — approve with `POST /approve/checkpoint_3` to trigger re-render
- Re-render produces `round_NN_{target_format}.docx` uploaded to Supabase Storage
- Does **not** re-run `fields_generator`, `content_reviewer`, or `compressor`

**Errors**:
- `409`: Session not in `completed` or `checkpoint_3_pending` state
- `422`: `edits` array is empty, exceeds 5 items, or an individual edit fails field validation

---

## Request/Response Examples

### Full Session Workflow

**Step 1: Create session**
```bash
curl -X POST http://127.0.0.1:8000/sessions \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "target_format": "giz",
    "source_filename": "cv.docx",
    "proposed_position": "Senior Water Engineer",
    "category": "Senior Expert"
  }'
```

**Step 2: Upload source CV**
```bash
curl -X POST http://127.0.0.1:8000/sessions/{session_id}/upload/source \
  -H "Authorization: Bearer <TOKEN>" \
  -F "file=@cv.docx"
```

**Step 3: Upload ToR (optional)**
```bash
curl -X POST http://127.0.0.1:8000/sessions/{session_id}/upload/tor \
  -H "Authorization: Bearer <TOKEN>" \
  -F "file=@tor.pdf"
```

**Step 4: Start processing**
```bash
curl -X POST http://127.0.0.1:8000/sessions/{session_id}/start \
  -H "Authorization: Bearer <TOKEN>"
```

**Step 5: Poll manifest (every 2-3 seconds)**
```bash
curl http://127.0.0.1:8000/sessions/{session_id}/manifest \
  -H "Authorization: Bearer <TOKEN>"
```

**Step 6: Approve checkpoint_1**
```bash
curl -X POST http://127.0.0.1:8000/sessions/{session_id}/approve/checkpoint_1 \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"notes": "Approved"}'
```

**Step 7: Approve checkpoint_2 & checkpoint_3**
```bash
# Same as step 6, with checkpoint_2 and checkpoint_3
```

**Step 8: Download output**
```bash
SIGNED_URL=$(curl http://127.0.0.1:8000/sessions/{session_id}/files/output/download-url \
  -H "Authorization: Bearer <TOKEN>" | jq -r '.signed_url')
curl "$SIGNED_URL" -o output.docx
```

---

### Field Edit Workflow (Post-Completion Revision)

**Step 1: Submit field edits (session must be `completed`)**
```bash
curl -X POST http://127.0.0.1:8000/sessions/{session_id}/field-edit \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "edits": [
      {
        "field_path": "key_qualifications[0]",
        "instruction": "Tighten this and keep factual wording"
      },
      {
        "field_path": "relevant_projects[2].location",
        "instruction": "Change to Nairobi, Kenya"
      }
    ]
  }'
```

**Step 2: Approve checkpoint_3 to trigger re-render**
> The `POST /field-edit` response already returns `status: "checkpoint_3_pending"` — no polling needed before this step.
```bash
curl -X POST http://127.0.0.1:8000/sessions/{session_id}/approve/checkpoint_3 \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"notes": "Approved"}'
```

**Step 4: Download revised output**
```bash
SIGNED_URL=$(curl http://127.0.0.1:8000/sessions/{session_id}/files/output/download-url \
  -H "Authorization: Bearer <TOKEN>" | jq -r '.signed_url')
curl "$SIGNED_URL" -o output_round2.docx
```

---

## Error Responses

All errors follow this format:

```json
{
  "detail": "Error description"
}
```

**Common Status Codes**:
- `200` — Success
- `201` — Created
- `400` — Bad request (invalid params, unsupported file type, etc.)
- `404` — Resource not found
- `409` — Conflict (wrong session status, checkpoint not pending, etc.)
- `422` — Unprocessable entity (validation error)
- `429` — Too many concurrent sessions
- `500` — Server error

---

## Rate Limiting

- **Max 3 concurrent active sessions per user** (status: `queued`, `processing`, any `checkpoint_*_pending`, `reviewer_blocked`)
- Older sessions in terminal states (`completed`, `failed`) don't count toward the limit

---

## Session Status Machine

```
queued
  ↓ (POST /start)
processing (Phase 1: cv_extractor + tor_summarizer parallel)
  ↓
checkpoint_1_pending
  ↓ (POST /tor/select-pool, then POST /approve/checkpoint_1)
processing (Phase 2: cv_tor_mapper)
  ↓
checkpoint_2_pending
  ↓ (POST /approve/checkpoint_2)
processing (Phase 3: fields_generator → content_reviewer → compressor)
  ↓
checkpoint_3_pending
  ↓ (POST /approve/checkpoint_3)
processing (Phase 4: renderer → upload output.docx)
  ↓
completed (output.docx ready for download)

Any phase → failed (if exception raised)

Post-completion field-edit revision:
completed
  ↓ (POST /field-edit — synchronous; returns checkpoint_3_pending immediately)
checkpoint_3_pending
  ↓ (POST /approve/checkpoint_3)
processing (Phase 4: renderer → upload revised output.docx)
  ↓
completed (revised output.docx ready, round incremented)
```

> **Note**: `reviewer_blocked` is a possible status after Phase 3 if the content reviewer
> flags high-severity issues. Use `POST /resolve` to resume from that state.
> `field_editor_pending` is a legacy status that may exist on older sessions; new sessions
> no longer enter this state.

---

## Pipeline Phases

| Phase | Agents / work | Input | Output | Halts at |
|-------|--------------|-------|--------|----------|
| 1 | cv_extractor + tor_summarizer (parallel) | CV + ToR files | cv_data.json, tor_data.json | checkpoint_1_pending |
| 2 | cv_tor_mapper | Extracted data | mapped_cv.json | checkpoint_2_pending |
| 3 | fields_generator → content_reviewer → compressor | Mapped CV | generated_fields.json (with review + compression blocks) | checkpoint_3_pending |
| 4 | Renderer | generated_fields.json["generated"] | output.docx uploaded to Storage | completed |
| Post-completion | field_editor (user-directed edits only, no LLM re-run of other agents) | generated_fields.json + user edit instructions | updated generated_fields.json | checkpoint_3_pending → Phase 4 |

---

## Environment Variables

Required in `.env`:
```
SUPABASE_URL=https://...
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_ROLE_KEY=...
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Notes

- **JWT Token**: Obtain from Supabase Auth (`supabase.auth.getSession()`)
- **Session ID**: UUID generated on `POST /sessions`
- **Storage Keys**: Use with Supabase Storage signed URLs (expire in 1 hour by default)
- **Revision Rounds**: Each `POST /field-edit` call increments the session's `round` counter; output files are labelled `round_01_giz.docx`, `round_02_giz.docx`, etc.
- **Field Edit vs. Resolve**: `POST /field-edit` is for post-completion user-directed revisions (LLM-mediated, entry condition `completed`). `POST /resolve` is for unblocking a `reviewer_blocked` pipeline run (caller-provided values, no LLM). They are independent.
- **Deprecated**: `POST /sessions/{id}/comments` is deprecated and replaced by `POST /sessions/{id}/field-edit`. The comments endpoint is kept for backward compatibility but emits `Deprecation: true`, `Sunset`, and `Link` response headers on every call.
- **Solvability**: Every finding in `GET /review` carries `solvability: "pipeline" | "human"`. Pipeline-solvable issues can be addressed via `POST /field-edit`; human-solvable issues require recruiter intervention via `POST /resolve`.
- **Warnings endpoint**: `GET /warnings` is additive — it does not modify any existing response shapes. It aggregates warnings that were always written to disk by the pipeline but previously never transmitted to the frontend. Returns `warnings: []` when the pipeline ran cleanly; safe to call at any pipeline stage after Phase 1. `GET /review` (generation quality) and `GET /warnings` (extraction/alignment/manifest/generation soft-flags) are complementary — neither replaces the other.
- **Compressor tuning**: Word-count targets and ratios come from **`FORMAT_PROFILES`** and orchestrator defaults (`PIPELINE_CONTEXT.md`). They are not end-user settings; **`POST /sessions` does not save optional `target_words` / `compression_ratio` fields to the DB** in the current implementation.
- **World Bank Format**: Supported via `target_format: "world_bank"` (requires `templates/WB-Template.docx` alongside the existing GIZ template at runtime).

---

## Support

For issues or questions, refer to:
- **Local dev**: Check `/health` endpoint
- **Logs**: uvicorn console output
- **Database**: Supabase SQL editor (sessions table)
- **Errors**: Check session status `error_message` field
