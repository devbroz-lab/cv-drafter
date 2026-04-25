# Dev 1 Checklist — CV Drafter

> Tick off items as you complete them. Items marked **[CRITICAL]** have a specific done-when condition. Items marked **[BOUNDARY]** are the handshake with Dev 2 — never change these. Items marked **[ADDED]** were not in the original context doc but are required.

---

## Phase 1 — Project Structure `Day 1`

- [ ] Create full directory structure — `backend/` with all subdirs, every package needs `__init__.py`
- [ ] Write `.python-version` — single line: `3.12.10`
- [ ] Write `.gitignore` — `.env`, `__pycache__/`, `*.pyc`, `.venv/`, `venv/`, `runs/*`, `!runs/.gitkeep`
- [ ] Write `.env.example` — all required key names with empty values, commit this, never `.env`
- [ ] Write `api/config.py` — pydantic-settings for env vars + runtime Python version check enforcing 3.12.x **[CRITICAL]**
- [ ] Write `api/server.py` — FastAPI app instance, mounts routers, adds CORS middleware, nothing else
- [ ] Write `api/routers/health.py` — `GET /health → { status: ok }`, no auth required
- [ ] Write `requirements.in` and compile `requirements.txt` — run `pip-compile requirements.in`, commit both files, never hand-edit `requirements.txt`
- [ ] Verify server starts cleanly — `uvicorn api.server:app --reload` → `/health` returns 200 **[CRITICAL]**

---

## Phase 2 — Supabase Setup `Day 1–2`

- [ ] Create Supabase project
- [ ] Run sessions table SQL — `id`, `user_id`, `status`, `target_format`, `page_limit`, `tor_text`, `job_description`, `recruiter_comments`, source paths, `error_message`, `round`, timestamps
- [ ] Enable Row Level Security + create policy — `'Users see own sessions'` using `auth.uid() = user_id`
- [ ] Create `cv-files` storage bucket — private, never public
- [ ] Verify DB connection from Python — insert a row, read it back, delete it **[CRITICAL]**

---

## Phase 3 — Auth Middleware `Day 2`

- [ ] Write `api/services/auth.py` — `get_current_user` FastAPI dependency, validates Supabase JWT from Authorization header
- [ ] Verify auth behaviour — no token → 401, invalid token → 401, valid Supabase JWT → user object returned **[CRITICAL]**

---

## Phase 4 — Database Service `Day 2–3`

- [ ] Write `api/services/database.py` — all Supabase DB calls here, no raw queries anywhere else in the codebase
- [ ] Implement `create_session()` — inserts row, returns session with uuid
- [ ] Implement `get_session(id, user_id)` — returns session or None, always scoped to `user_id`, never bare id lookup
- [ ] Implement `set_processing(id)`
- [ ] Implement `set_done(id, output_storage_path)`
- [ ] Implement `set_failed(id, error_message)`
- [ ] Implement `increment_round(id)` — `round += 1`, called before each revision run
- [ ] Implement `count_active_sessions(user_id)` — count rows where status IN (`pending`, `processing`) for this user, used for rate limiting **[ADDED]**

---

## Phase 5 — Storage Service `Day 3`

- [ ] Write `api/services/storage.py` — all Supabase Storage calls here, nothing else touches storage directly
- [ ] Implement `upload_input(session_id, filename, bytes)` — stores at `cv-files/{session_id}/input/{filename}`
- [ ] Implement `upload_output(session_id, round, target_format, bytes)` — stores at `cv-files/{session_id}/output/round_{NN}_{format}.docx`
- [ ] Implement `get_signed_url(storage_path)` — returns fresh time-limited URL, generate on every status call, do not store, set expiry to 1 hour
- [ ] Verify upload + download works — upload a `.docx`, get signed URL, paste in browser, file downloads correctly **[CRITICAL]**

---

## Phase 6 — API Endpoints + Async Layer `Day 3–4`

- [ ] Write `api/models/requests.py` — Pydantic models for all request/response shapes (`CreateSessionResponse`, `StatusResponse` etc.)
- [ ] Implement `POST /sessions` — validate file type (`.docx` or `.pdf` only → 400 otherwise), check active session count → 429 if limit hit, upload input file, create DB record, schedule background task, return `{ id, status: processing }` immediately **[CRITICAL]**
- [ ] Implement `GET /sessions/{id}/status` — fetch session scoped to current user → 404 if not found, return `status`, `round`, `target_format`, `download_url` (fresh signed URL only when done), `error_message` (only when failed)
- [ ] Implement `POST /sessions/{id}/comments` — 400 if status != done, increment round, schedule revision background task, return `{ id, status: processing }`
- [ ] Write `process_session()` background task — `set_processing` → `run_pipeline` → `upload_output` → `set_done`, catch all exceptions → `set_failed`, delete temp file in `finally` block **[CRITICAL]**
- [ ] Write `process_revision()` background task — `increment_round` → `set_processing` → `run_revision` → `upload_output` → `set_done`, same exception handling and cleanup **[ADDED]**
- [ ] Add rate limit check before session creation — `count_active_sessions(user_id) >= 3` → raise 429, protects against runaway OpenAI costs **[ADDED]**
- [ ] Add temp file cleanup in `finally` block — `input_path.unlink(missing_ok=True)`, runs whether pipeline succeeds or fails, prevents disk fill on long-running server **[ADDED]**
- [ ] Verify full stub flow end-to-end — upload → processing → done → signed URL → file downloads, test failure path too: bad file → `set_failed` → `error_message` returned **[CRITICAL]**

---

## Phase 7 — Pipeline Stub + Startup Recovery `Day 4`

- [ ] Write stub `pipeline/runner.py` — `asyncio.sleep(3)` then copy input bytes as output, real logic is Dev 2's job
- [ ] Lock `run_pipeline()` signature — never change: `(input_path, target_format, page_limit, tor_text, job_description, recruiter_comments) → Path` **[BOUNDARY]**
- [ ] Lock `run_revision()` signature — never change: `(session_id, new_comment, target_format, page_limit, tor_text, job_description) → Path` **[BOUNDARY]**
- [ ] Add startup recovery on server boot — on FastAPI startup event, find all sessions with `status=processing`, reset to `failed`, prevents ghost sessions after crashes or redeploys **[ADDED]**

---

## Phase 8 — File Extractor `Day 5`

- [ ] Write `pipeline/extractor/docx_extractor.py` — `python-docx`, output tagged plain text: `[HEADING]` `[BOLD]` `[NORMAL]` `[TABLE N]` `[END TABLE]`, no AI, purely mechanical
- [ ] Write `pipeline/extractor/pdf_extractor.py` — `pdfplumber`, same tag format, handle multi-page
- [ ] Write `pipeline/extractor/__init__.py` — `extract_text(path)` routes to docx or pdf by suffix, raises `ValueError` for unsupported types
- [ ] Test on `sample_giz.docx` — Merita Kostari CV, all sections present in output, CEFR language levels visible, project rows readable **[CRITICAL]**
- [ ] Test on `sample_wb.docx` — Jamil Musleh CV, employment record and relevant projects both extracting as separate sections **[CRITICAL]**
- [ ] Share tagged output with Dev 2 early — Dev 2 cannot test his extractor agent without real tagged text, give him a draft output even before Phase 8 is fully complete **[ADDED]**

---

## Deployment

### Backend — FastAPI
| Option | Notes |
|---|---|
| **Railway** *(recommended)* | Deploy directly from GitHub, zero config, runs Docker or Nixpacks automatically. Supports persistent disk for `runs/` temp dir. Cheapest viable option at this stage. |
| Render *(alternative)* | Similar to Railway. Free tier spins down after inactivity causing cold start delays — use paid tier from day one for any real customer. |

### Frontend — React/Vite
| Option | Notes |
|---|---|
| **Vercel** *(recommended)* | Push to GitHub, done. Automatic preview deployments per branch. Free tier sufficient until significant traffic. Set `VITE_API_URL` env var to point at your Railway backend URL. |
| Netlify *(alternative)* | Functionally identical to Vercel for a Vite app. Either works. |

### Before going live — do both of these or auth and API calls will fail in production
- [ ] Add frontend domain to Supabase Auth allowed redirect URLs
- [ ] Add frontend domain to FastAPI CORS origins in `api/server.py`

---

*38 tasks across 8 phases. Tags: [CRITICAL] = has a specific done-when condition. [BOUNDARY] = handshake with Dev 2, never change. [ADDED] = not in original context doc but required.*