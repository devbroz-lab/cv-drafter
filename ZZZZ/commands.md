uvicorn api.server:app --reload --host 127.0.0.1 --port 8000

curl http://127.0.0.1:8000/health

## APIs

### GET /health
What it does: returns a simple server health response.
When to use: quick check that FastAPI is running and reachable.

curl -sS http://127.0.0.1:8000/health

### Auth-protected backend APIs

Use this header on all protected backend routes:

-H "Authorization: Bearer YOUR_ACCESS_TOKEN"

### POST /sessions
What it does: creates a new processing session row in Supabase for one CV workflow.
When to use: first step before uploading files or starting processing.

curl -sS -X POST http://127.0.0.1:8000/sessions \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"target_format":"giz","source_filename":"cv.pdf"}'

### GET /sessions/{session_id}/status
What it does: fetches the current session record, including status, filenames, storage keys, and timestamps.
When to use: polling progress or checking what has already been uploaded/processed.

curl -sS http://127.0.0.1:8000/sessions/SESSION_ID/status \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"

### PATCH /sessions/{session_id}/status
What it does: updates the backend-managed state of a session (`queued`, `processing`, `completed`, `failed`).
When to use: internal/testing use when you need to move a session through pipeline states.

curl -sS -X PATCH http://127.0.0.1:8000/sessions/SESSION_ID/status \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"processing"}'

### POST /sessions/{session_id}/upload/source
What it does: uploads the main CV/source file into Supabase Storage and stores its key on the session.
When to use: after creating a session, before starting processing.

curl -sS -X POST "http://127.0.0.1:8000/sessions/SESSION_ID/upload/source" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -F "file=@/absolute/path/to/cv.pdf"

### POST /sessions/{session_id}/upload/tor
What it does: uploads the optional Terms of Reference file into Supabase Storage and stores its key on the session.
When to use: only when the workflow includes a ToR/JD/reference document.

curl -sS -X POST "http://127.0.0.1:8000/sessions/SESSION_ID/upload/tor" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -F "file=@/absolute/path/to/tor.pdf"

### GET /sessions/{session_id}/files/source/download-url
What it does: generates a temporary signed URL for the uploaded CV/source file.
When to use: when you need to download or inspect the uploaded source without making the bucket public.

curl -sS "http://127.0.0.1:8000/sessions/SESSION_ID/files/source/download-url" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"

### GET /sessions/{session_id}/files/tor/download-url
What it does: generates a temporary signed URL for the uploaded ToR file.
When to use: when you need secure temporary access to the uploaded ToR.

curl -sS "http://127.0.0.1:8000/sessions/SESSION_ID/files/tor/download-url" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"

### GET /sessions/{session_id}/files/output/download-url
What it does: generates a temporary signed URL for the extracted output JSON stored in Supabase Storage.
When to use: after processing completes, when you want to fetch the extracted text artifact from the cloud.

curl -sS "http://127.0.0.1:8000/sessions/SESSION_ID/files/output/download-url" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"

### POST /sessions/{session_id}/start
What it does: marks a queued session as processing and kicks off the background orchestrator task.
When to use: after the source file is uploaded and the session is ready to enter the extraction/pipeline stage.

curl -sS -X POST "http://127.0.0.1:8000/sessions/SESSION_ID/start" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"

## Supabase Auth APIs

### Signup
What it does: creates a new Supabase Auth user with email/password.
When to use: one-time setup for a new test or real user before login.

curl -sS "https://YOUR_PROJECT_REF.supabase.co/auth/v1/signup" \
  -H "apikey: YOUR_ANON_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"yourpassword"}'

### Login
What it does: exchanges email/password for an access token, refresh token, and user session data.
When to use: before calling protected backend APIs.

curl -sS "https://YOUR_PROJECT_REF.supabase.co/auth/v1/token?grant_type=password" \
  -H "apikey: YOUR_ANON_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"yourpassword"}'

### Refresh token
What it does: gets a fresh access token using a valid refresh token.
When to use: when the current access token has expired and the client needs a new one.

curl -sS "https://YOUR_PROJECT_REF.supabase.co/auth/v1/token?grant_type=refresh_token" \
  -H "apikey: YOUR_ANON_KEY" \
  -H "Content-Type: application/json" \
  -d '{"refresh_token":"YOUR_REFRESH_TOKEN"}'