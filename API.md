# CV Reformatter Backend API Documentation

## Overview

The CV Reformatter API processes CVs through a 6-agent AI pipeline, producing formatted Word documents tailored for international development donors (GIZ, World Bank). The pipeline includes human approval checkpoints and a revision workflow.

**Base URL**: `http://127.0.0.1:8000`  
**Authentication**: Supabase JWT bearer token (required for all endpoints except `/health`)

---

## Quick Start

### 1. Run the Server
```bash
cd /Users/qamarali/Desktop/backend
source venv_312/bin/activate
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
- `target_format` *(required, enum)*: `"giz"` or `"world_bank"` (World Bank not yet supported)
- `source_filename` *(required, string)*: Name of the CV file (e.g., `"cv.docx"`, `"cv.pdf"`)
- `tor_filename` *(optional, string)*: Name of the Terms of Reference file
- `proposed_position` *(optional, string)*: Position title for the formatted CV
- `category` *(optional, string)*: Expert category (e.g., "Senior Expert", "Junior Expert")
- `employer` *(optional, string)*: Consulting firm or employer name
- `years_with_firm` *(optional, string)*: Years at firm (e.g., "5", "5+", "<1")
- `page_limit` *(optional, integer)*: Max output pages (1–100; default 4 for GIZ)
- `job_description` *(optional, string)*: Free-text job description
- `recruiter_comments` *(optional, string)*: Initial recruiter feedback

**Response** (201):
```json
{
  "session_id": "20260425_143022_a1b2",
  "status": "queued"
}
```

**Errors**:
- `400`: World Bank format not yet available
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
- `checkpoint_3_pending` — Agents 4, 5, 6 done, awaiting approval
- `reviewer_blocked` — Content reviewer flagged high-severity issues
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

#### `POST /sessions/{session_id}/approve/{checkpoint}`
Approve a checkpoint and resume the next phase.

**Parameters**:
- `checkpoint` *(required, enum)*: `checkpoint_1`, `checkpoint_2`, or `checkpoint_3`

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

### Checkpoint Data

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
      "field": "generated_fields.0.content",
      "issue": "Unverifiable claim: '10-year track record' not found in CV",
      "recommendation": "Remove or rephrase with grounded evidence"
    }
  ],
  "low_severity": [
    {
      "field": "generated_fields.1.content",
      "issue": "Passive language: 'was responsible for'",
      "original": "was responsible for designing the framework",
      "fixed": "Designed the framework"
    }
  ],
  "passed": false,
  "generation_warnings": [
    "More than 1 bullet has source='tor' (weak CV grounding)"
  ]
}
```

---

#### `GET /sessions/{session_id}/output`
Get the final generated CV data (after all agents complete).

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

### Content Resolution (Reviewer Blocked)

#### `POST /sessions/{session_id}/resolve`
Resolve high-severity content issues and resume the pipeline.

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

### Revision Workflow

#### `POST /sessions/{session_id}/comments`
Submit recruiter feedback to trigger a revision run.

**Preconditions**:
- Session status must be `completed`

**Request Body** (application/json):
```json
{
  "comment": "Please emphasize renewable energy expertise more strongly"
}
```

**Parameters**:
- `comment` *(required, string)*: Recruiter feedback (min 1 character)

**Response** (200):
```json
{
  "session_id": "20260425_143022_a1b2",
  "status": "processing",
  "round": 2,
  "message": "Revision queued. Poll /status for updates."
}
```

**Behavior**:
- Appends comment to `recruiter_comments` with `[Round N]: ` prefix
- Re-runs Phase 3 (Fields Generator → Content Reviewer → Compressor)
- Halts at `checkpoint_3_pending` for final approval before re-rendering
- Increments `round` counter

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

**Step 7: (If reviewer blocked) Resolve issues**
```bash
curl -X POST http://127.0.0.1:8000/sessions/{session_id}/resolve \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "overrides": {"generated_fields.0.content": "Fixed text"},
    "force_pass": false
  }'
```

**Step 8: Approve checkpoint_2 & checkpoint_3**
```bash
# Same as step 6, with checkpoint_2 and checkpoint_3
```

**Step 9: Download output**
```bash
SIGNED_URL=$(curl http://127.0.0.1:8000/sessions/{session_id}/files/output/download-url \
  -H "Authorization: Bearer <TOKEN>" | jq -r '.signed_url')
curl "$SIGNED_URL" -o output.docx
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
processing (Phase 1)
  ↓
checkpoint_1_pending
  ↓ (POST /approve/checkpoint_1)
processing (Phase 2)
  ↓
checkpoint_2_pending
  ↓ (POST /approve/checkpoint_2)
processing (Phase 3)
  ├→ reviewer_blocked (if high-severity issues)
  │   ↓ (POST /resolve)
  │   processing (resume compressor)
  │   ↓
  └→ checkpoint_3_pending (if reviewer passed)
     ↓ (POST /approve/checkpoint_3)
     processing (Phase 4 - renderer)
     ↓
     completed (output.docx ready for download)

Any phase → failed (if exception raised)
completed → processing (POST /comments for revision)
```

---

## Pipeline Phases

| Phase | Agents | Input | Output | Checkpoint |
|-------|--------|-------|--------|-----------|
| 1 | 1, 2 | CV + ToR files | cv_data.json, tor_data.json | checkpoint_1 |
| 2 | 3 | Extracted data | mapped_cv.json | checkpoint_2 |
| 3 | 4, 5, 6 | Mapped CV | generated_fields.json | checkpoint_3 / reviewer_blocked |
| 4 | Renderer | Generated fields | output.docx | (complete) |

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
- **Revision Rounds**: Each comment round increments the session's `round` counter; output files are labeled `round_01_giz.docx`, `round_02_giz.docx`, etc.
- **World Bank Format**: Not yet supported; API returns 400 if requested

---

## Support

For issues or questions, refer to:
- **Local dev**: Check `/health` endpoint
- **Logs**: uvicorn console output
- **Database**: Supabase SQL editor (sessions table)
- **Errors**: Check session status `error_message` field
