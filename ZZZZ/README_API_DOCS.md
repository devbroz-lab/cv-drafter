# API Documentation Files

This directory contains comprehensive API documentation and examples.

## Files

### 1. **API.md** (Main Documentation)
Complete API reference with:
- All 16 endpoints documented
- Request/response examples with JSON
- Parameter descriptions
- Error codes and status codes
- Session status machine diagram
- Pipeline phases explanation
- Quick start guide

**Read this first** for a complete understanding of the API.

### 2. **api_quick_reference.sh** (Bash Commands)
Shell script with ready-to-use `curl` commands for:
- Health check
- Creating sessions
- Uploading files
- Starting processing
- Approving checkpoints
- Resolving review issues
- Downloading output
- Revision workflow

**Usage**:
```bash
# Edit TOKEN and SESSION_ID variables in the script
nano api_quick_reference.sh

# Then run individual curl commands from the script
```

### 3. **api_client_example.py** (Python Client)
Python class (`CVReformatterClient`) that wraps all API operations:
- Object-oriented API client
- Error handling with `raise_for_status()`
- Helper methods for each endpoint
- Full example workflow at the bottom

**Usage**:
```python
from api_client_example import CVReformatterClient

client = CVReformatterClient("http://127.0.0.1:8000", TOKEN)
session = client.create_session(
    target_format="giz",
    source_filename="cv.docx",
    proposed_position="Senior Expert"
)
print(session["session_id"])
```

---

## Quick Links

| Endpoint | Method | Path |
|----------|--------|------|
| Health Check | GET | `/health` |
| Create Session | POST | `/sessions` |
| Get Status | GET | `/sessions/{id}/status` |
| Upload CV | POST | `/sessions/{id}/upload/source` |
| Upload ToR | POST | `/sessions/{id}/upload/tor` |
| Start Processing | POST | `/sessions/{id}/start` |
| Poll Progress | GET | `/sessions/{id}/manifest` |
| Approve Checkpoint | POST | `/sessions/{id}/approve/{checkpoint}` |
| View Review Issues | GET | `/sessions/{id}/review` |
| Resolve Issues | POST | `/sessions/{id}/resolve` |
| Get Final Output | GET | `/sessions/{id}/output` |
| Download Output | GET | `/sessions/{id}/files/output/download-url` |
| Submit Revision | POST | `/sessions/{id}/comments` |

---

## Common Workflows

### Workflow 1: Simple Processing (No Issues)
1. `POST /sessions` → create
2. `POST /upload/source` → upload CV
3. `POST /start` → begin Phase 1
4. Poll `/manifest` until `checkpoint_1_pending`
5. `POST /approve/checkpoint_1` → Phase 2
6. Poll `/manifest` until `checkpoint_2_pending`
7. `POST /approve/checkpoint_2` → Phase 3
8. Poll `/manifest` until `checkpoint_3_pending` (if no reviewer block)
9. `POST /approve/checkpoint_3` → Phase 4 (renderer)
10. Poll `/status` until `completed`
11. `GET /files/output/download-url` → download

### Workflow 2: With Reviewer Block
Same as above, but at step 8:
- If `reviewer_blocked=true` in manifest
- `GET /review` → check issues
- `POST /resolve` → fix and resume
- Continue from step 9

### Workflow 3: Revision
After session is `completed`:
1. `POST /comments` → submit feedback
2. Session resumes Phase 3
3. Poll `/manifest` until `checkpoint_3_pending`
4. `POST /approve/checkpoint_3` → re-render
5. Poll `/status` until `completed`
6. Download new output (will be labeled `round_02_...`)

---

## Environment Setup

```bash
# Start the server
cd /Users/qamarali/Desktop/backend
source venv_312/bin/activate
uvicorn api.server:app --reload --host 127.0.0.1 --port 8000

# In another terminal, test with curl
curl http://127.0.0.1:8000/health

# Or use the Python client example
python ZZZZ/api_client_example.py
```

---

## Debugging Tips

- **Check server is running**: `curl http://127.0.0.1:8000/health`
- **Check session error**: `curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/sessions/{id}/status | jq '.error_message'`
- **View all steps**: `curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/sessions/{id}/manifest | jq '.steps'`
- **Check if blocked**: `curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/sessions/{id}/manifest | jq '.reviewer_blocked'`

---

## Notes

- **JWT Token**: Required for all endpoints except `/health`. Get from Supabase Auth.
- **Session ID**: UUID returned from `POST /sessions`. Use this for all subsequent calls.
- **Rate Limit**: Max 3 concurrent active sessions per user.
- **Storage Keys**: Signed URLs expire in 1 hour by default (configurable).
- **Revision Rounds**: Each comment increments `round` counter; output files labeled `round_NN_giz.docx`.

---

## See Also

- **Full API.md**: Complete endpoint documentation
- **pyproject.toml**: Dependencies and scripts
- **CLAUDE.md**: Architecture and project overview
