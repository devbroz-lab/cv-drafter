# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CV Reformatting SaaS backend: ingests raw CVs (PDF/DOCX) and optional Terms of Reference, runs an AI pipeline, and produces formatted Word documents for international development donors (GIZ, World Bank formats).

**Stack**: FastAPI 0.115.12 · Python 3.12.13 (strictly pinned) · Supabase (Auth + Postgres + Storage) · Ruff

## Commands

```bash
# Install (must use Python 3.12.13 exactly)
pip install -e ".[dev]"

# Run dev server
uvicorn api.server:app --reload --host 127.0.0.1 --port 8000

# Lint
ruff check api pipeline templates

# Format
ruff format api pipeline templates

# Tests
pytest
```

**Python version**: The project pins `3.12.13` in `.python-version`. Use pyenv or uv if your system default differs — other 3.x versions will break.

## Architecture

```
Client → FastAPI (api/) → Supabase Auth/Postgres/Storage
                       → BackgroundTasks → pipeline/orchestrator.py
                                        → pipeline/agents/     (AI agents — Dev 2)
                                        → templates/           (Word rendering — Dev 3)
```

**Session state machine**: `queued` → `processing` → `completed` | `failed`

The orchestrator (`pipeline/orchestrator.py`) runs in a FastAPI `BackgroundTasks` job. It extracts text from uploaded files, writes `extraction.json`, runs agents to populate a `CVData` struct, then hands off to a template renderer to produce the output `.docx`.

### Key Layers

| Layer | Path | Responsibility |
|-------|------|---------------|
| API / Auth / Storage | `api/` | Routes, Supabase auth dependency, file upload/download, session CRUD |
| AI Agents | `pipeline/agents/` | Extractor → Mapper → Condenser → Reviewer → Tasks agents |
| Word Templates | `templates/` | GIZ and World Bank `.docx` rendering from `CVData` |
| Shared Contract | `models.py` (root) | `CVData` Pydantic schema — **do not modify without team agreement** |

### Database

No ORM — direct `supabase-py` client calls. Single `sessions` table with UUID primary key, `user_id` FK to `auth.users`, status enum, storage key columns, and timestamps. See `ZZZZ/sessions_add_auth.sql` and `ZZZZ/sessions_add_storage.sql` for schema migrations.

### Auth

All routes except `GET /health` require a Supabase JWT bearer token. The `get_current_user` FastAPI dependency (in `api/services/auth.py`) validates it via `auth.get_user(token)`.

### Storage

Files stored in Supabase Storage bucket (`cv-uploads` by default) at path `{session_id}/{kind}/{filename}` where `kind` ∈ `{source, tor, output}`. Signed download URLs expire in 60s–7 days.

## Important Conventions

- **`models.py` is a locked contract** shared across agents and renderers. Don't change field names or types without agreement from all three developers.
- **Three-developer split**: Dev 1 owns `api/`; Dev 2 owns `pipeline/agents/`; Dev 3 owns `templates/`. Be aware of ownership when making changes.
- **Dependencies are pinned exactly** in `pyproject.toml`. Don't loosen version pins without checking transitive constraints (e.g., `pytest-asyncio==0.24.0` requires `pytest>=8.2`).
- **Ruff config**: line length 100, rules E/F/I/UP/B/SIM, target py312.
- Local session artifacts are written to `runs/{session_id}/` during processing.
- API endpoint examples with curl are documented in `ZZZZ/commands.md`.
- Architecture decisions and gotchas are logged in `memory.md` at the project root.
