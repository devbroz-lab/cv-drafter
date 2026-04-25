# CV Reformatter Backend - Documentation Index

## Quick Navigation

| Document | Location | Purpose |
|----------|----------|---------|
| **[API.md](./API.md)** | Root | Complete API reference with all 16 endpoints, examples, and workflows |
| **[README_API_DOCS.md](./ZZZZ/README_API_DOCS.md)** | ZZZZ/ | Summary and quick links for all API docs |
| **[api_quick_reference.sh](./ZZZZ/api_quick_reference.sh)** | ZZZZ/ | Ready-to-use bash/curl commands (executable) |
| **[api_client_example.py](./ZZZZ/api_client_example.py)** | ZZZZ/ | Python client class with full workflow example |
| **[CLAUDE.md](./CLAUDE.md)** | Root | Architecture, project overview, and conventions |
| **[sessions_schema_v5.sql](./ZZZZ/sessions_schema_v5.sql)** | ZZZZ/ | Database migration (run in Supabase) |

---

## Getting Started (5 minutes)

### 1. Set Up Environment
```bash
cd /Users/qamarali/Desktop/backend
source venv_312/bin/activate
uvicorn api.server:app --reload --host 127.0.0.1 --port 8000
```

### 2. Test Health Endpoint
```bash
curl http://127.0.0.1:8000/health
```

### 3. Run Database Migration
- Open Supabase SQL editor
- Paste contents of `ZZZZ/sessions_schema_v5.sql`
- Execute

### 4. Try the API
- **Option A (Bash)**: Use commands from `ZZZZ/api_quick_reference.sh`
- **Option B (Python)**: Run `python ZZZZ/api_client_example.py`

---

## API Overview

### 16 Endpoints in 4 Categories

#### Health (1)
- `GET /health` — Server liveness

#### Session Management (4)
- `POST /sessions` — Create session
- `GET /sessions/{id}/status` — Get status
- `PATCH /sessions/{id}/status` — Update status
- `POST /sessions/{id}/start` — Begin processing

#### File Operations (5)
- `POST /sessions/{id}/upload/source` — Upload CV
- `POST /sessions/{id}/upload/tor` — Upload ToR
- `GET /sessions/{id}/files/source/download-url` — Get CV download URL
- `GET /sessions/{id}/files/tor/download-url` — Get ToR download URL
- `GET /sessions/{id}/files/output/download-url` — Get output download URL

#### Pipeline Control (6)
- `GET /sessions/{id}/manifest` — Poll progress
- `POST /sessions/{id}/approve/{checkpoint}` — Approve checkpoint
- `GET /sessions/{id}/review` — View reviewer issues
- `POST /sessions/{id}/resolve` — Resolve issues
- `GET /sessions/{id}/output` — Get final data
- `POST /sessions/{id}/comments` — Submit revision feedback

---

## Session State Machine

```
queued
  ↓ (POST /start)
processing (Phase 1: extraction)
  ↓
checkpoint_1_pending (Agents 1 & 2 done)
  ↓ (POST /approve/checkpoint_1)
processing (Phase 2: mapping)
  ↓
checkpoint_2_pending (Agent 3 done)
  ↓ (POST /approve/checkpoint_2)
processing (Phase 3: generation → review → compression)
  ├→ reviewer_blocked (high-severity issues)
  │   ↓ (POST /resolve)
  │   processing (resume compressor)
  │   ↓
  └→ checkpoint_3_pending (Agents 4, 5, 6 done)
     ↓ (POST /approve/checkpoint_3)
     processing (Phase 4: renderer)
     ↓
     completed (output.docx ready)

Any phase → failed (exception raised)
completed → processing (POST /comments for revision)
```

---

## Complete Workflow Example (Python)

```python
from ZZZZ.api_client_example import CVReformatterClient

# Initialize
client = CVReformatterClient("http://127.0.0.1:8000", YOUR_TOKEN)

# 1. Create session
session = client.create_session(
    target_format="giz",
    source_filename="cv.docx",
    proposed_position="Senior Water Engineer",
    category="Senior Expert",
    employer="ABC Consulting"
)
session_id = session["session_id"]

# 2. Upload files
client.upload_cv(session_id, "/path/to/cv.docx")
client.upload_tor(session_id, "/path/to/tor.pdf")  # optional

# 3. Start processing
client.start_processing(session_id)

# 4. Wait for checkpoint 1 & approve
client.wait_for_checkpoint(session_id, "checkpoint_1")
client.approve_checkpoint(session_id, "checkpoint_1")

# 5. Wait for checkpoint 2 & approve
client.wait_for_checkpoint(session_id, "checkpoint_2")
client.approve_checkpoint(session_id, "checkpoint_2")

# 6. Wait for checkpoint 3 (may be blocked by reviewer)
manifest = client.get_manifest(session_id)
if manifest["reviewer_blocked"]:
    review = client.get_review(session_id)
    # Fix issues...
    client.resolve_review(session_id, force_pass=True)
    client.wait_for_checkpoint(session_id, "checkpoint_3")

# 7. Approve checkpoint 3 (triggers renderer)
client.approve_checkpoint(session_id, "checkpoint_3")

# 8. Wait for completion & download
while True:
    status = client.get_session_status(session_id)
    if status["status"] == "completed":
        break
    time.sleep(3)

# 9. Get output
output = client.get_output(session_id)
print(f"Position: {output['cv_data']['proposed_position']}")

# 10. Download Word document
url = client.get_download_url(session_id, "output")
import urllib.request
urllib.request.urlretrieve(url, "output.docx")
```

---

## Complete Workflow Example (Bash)

See `ZZZZ/api_quick_reference.sh` for complete curl commands.

Quick example:
```bash
TOKEN="<SUPABASE_JWT>"
BASE_URL="http://127.0.0.1:8000"

# Create session
SESSION=$(curl -s -X POST "$BASE_URL/sessions" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "target_format": "giz",
    "source_filename": "cv.docx",
    "proposed_position": "Senior Expert"
  }')
SESSION_ID=$(echo $SESSION | jq -r '.session_id')

# Upload CV
curl -X POST "$BASE_URL/sessions/$SESSION_ID/upload/source" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@cv.docx"

# Start processing
curl -X POST "$BASE_URL/sessions/$SESSION_ID/start" \
  -H "Authorization: Bearer $TOKEN"

# Poll progress
curl "$BASE_URL/sessions/$SESSION_ID/manifest" \
  -H "Authorization: Bearer $TOKEN" | jq '.steps'

# Approve checkpoints (repeat for each)
curl -X POST "$BASE_URL/sessions/$SESSION_ID/approve/checkpoint_1" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"notes": "Approved"}'
```

---

## API Parameters Reference

### Session Creation (`POST /sessions`)
```json
{
  "target_format": "giz",                    // required: "giz" or "world_bank"
  "source_filename": "cv.docx",              // required: filename with extension
  "tor_filename": "tor.pdf",                 // optional
  "proposed_position": "Senior Engineer",    // optional: job title
  "category": "Senior Expert",               // optional: expert level
  "employer": "ABC Consulting",              // optional: firm name
  "years_with_firm": "5",                    // optional: string (e.g., "5", "5+", "<1")
  "page_limit": 4,                           // optional: 1-100, default 4
  "job_description": "Lead water projects",  // optional: free text
  "recruiter_comments": "Initial feedback"   // optional: free text
}
```

### Approve Checkpoint (`POST /sessions/{id}/approve/{checkpoint}`)
```json
{
  "notes": "Looks good, proceed"  // optional: approval notes
}
```

### Resolve Review (`POST /sessions/{id}/resolve`)
```json
{
  "overrides": {
    "generated_fields.0.content": "Fixed bullet text",
    "generated_fields.1.content": "Another fix"
  },
  "force_pass": false  // true to bypass remaining issues
}
```

### Submit Revision (`POST /sessions/{id}/comments`)
```json
{
  "comment": "Please emphasize renewable energy expertise more"
}
```

---

## Debugging & Troubleshooting

### Server Issues
```bash
# Check if server is running
curl http://127.0.0.1:8000/health

# Check server logs (look at uvicorn output for errors)
# Common issues:
# - Port 8000 already in use: kill with pkill -f uvicorn
# - ANTHROPIC_API_KEY not set: check .env file
# - Supabase connection: check SUPABASE_* env vars
```

### Session Issues
```bash
# View session status
curl -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/sessions/$SESSION_ID/status | jq '.error_message'

# View all pipeline steps
curl -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/sessions/$SESSION_ID/manifest | jq '.steps'

# Check if reviewer blocked
curl -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/sessions/$SESSION_ID/manifest | jq '.reviewer_blocked'
```

### File Upload Issues
```bash
# Check if CV was uploaded
curl -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/sessions/$SESSION_ID/status | jq '.source_storage_key'

# Only .docx and .pdf are accepted
```

---

## Environment Variables

Required in `.env`:
```bash
SUPABASE_URL=https://...
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_ROLE_KEY=...
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Rate Limiting

- **Max 3 concurrent active sessions per user**
- Active = `queued`, `processing`, `checkpoint_*_pending`, `reviewer_blocked`
- Terminal = `completed`, `failed` (don't count toward limit)

---

## Support & Resources

- **Full API docs**: See [API.md](./API.md)
- **Architecture**: See [CLAUDE.md](./CLAUDE.md)
- **Project structure**: See `README.md` (if exists)
- **Database schema**: See `ZZZZ/sessions_schema_v*.sql` files
