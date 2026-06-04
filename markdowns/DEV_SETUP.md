# Development vs production environments

Tailor-it uses **two isolated stacks**: different Supabase projects, different Railway deployments, and different env files. **Git branch** selects which hosted stack you deploy to.

| | **Production** | **Development** |
|---|----------------|-----------------|
| **Git branch** | `main` | `develop` |
| **Railway** | Prod API + prod UI services | Dev API + dev UI services |
| **Supabase** | Existing prod project | **New** dev project (you create) |
| **Secrets** | Railway prod variables | Railway dev variables (never copy JWT secrets from prod) |
| **Local `.env`** | Optional `cv-drafter/.env.production.local` (gitignored) | `cv-drafter/.env` → **dev** Supabase while coding |

When coding locally, point `.env` at the **dev** Supabase project only. Deploy `develop` to Railway dev; merge to `main` only when ready for production.

---

## What you need to set up (one-time)

### 1. Supabase — dev project

1. Create a new project (e.g. `tailor-it-dev`).
2. In **SQL Editor**, run **in this order** (enable RLS when Supabase prompts on new tables):
   - `api/migrations/000_sessions_table_schema.sql` — base `sessions` table (required first)
   - `api/migrations/001_create_app_auth_tables.sql` — `app_users`, refresh tokens
   - `api/migrations/002_sessions_user_fk_app_users.sql` — `sessions.user_id` → `app_users`
   - `api/migrations/003_metering_tables.sql` — credits / metering
3. **Storage** → create bucket `cv-uploads` (same name as prod is fine inside this project).
4. Save from **Project Settings → API**:
   - Project URL → `SUPABASE_URL`
   - `anon` key → `SUPABASE_ANON_KEY`
   - `service_role` key → `SUPABASE_SERVICE_ROLE_KEY`

Prod project credentials stay in Railway **production** only — do not put prod keys in dev `.env`.

### 2. Railway — map branches to services

Create **separate services** (or environments) so `develop` never deploys to prod URLs:

| Service | Root directory | Deploy branch | Notes |
|---------|----------------|---------------|--------|
| `tailor-it-api-prod` | `cv-drafter` | `main` | Production API |
| `tailor-it-api-dev` | `cv-drafter` | `develop` | Development API |
| `tailor-it-ui-prod` | `cv-drafter-ui` | `main` | Production frontend |
| `tailor-it-ui-dev` | `cv-drafter-ui` | `develop` | Development frontend |

In each service: **Settings → Source** → set the branch. **Variables** → paste env vars for that environment only.

After first deploy, note the public URLs (e.g. `https://tailor-it-api-dev.up.railway.app`).

### 3. Backend env vars (Railway)

**Production** (`main` / prod service) — keep current values.

**Development** (`develop` / dev service) — same variable **names**, **dev** values:

```env
SUPABASE_URL=<dev project URL>
SUPABASE_ANON_KEY=<dev anon>
SUPABASE_SERVICE_ROLE_KEY=<dev service role>
SUPABASE_STORAGE_BUCKET=cv-uploads

ANTHROPIC_API_KEY=<key — can share with prod; monitor spend>

JWT_SECRET=<generate new — not prod>
JWT_REFRESH_SECRET=<generate new — not prod>

GOOGLE_CLIENT_ID=<same or separate OAuth client>
MICROSOFT_CLIENT_ID=<same or separate>

CORS_ORIGINS=https://<dev-ui-host>,http://localhost:5173
AUTH_EMAIL_ALLOWLIST=<team emails for dev testing>

# Optional on dev only
DEBUG=true
```

### 4. Frontend env vars (Railway dev UI)

Set at **build time** for the `cv-drafter-ui` dev service:

```env
VITE_API_BASE_URL=https://<dev-api-host>
VITE_AUTH_API_BASE_URL=https://<dev-api-host>/auth
VITE_GOOGLE_CLIENT_ID=<same as backend>
VITE_MICROSOFT_CLIENT_ID=<same as backend>
```

Prod UI service uses prod API URL and deploys from `main`.

### 5. OAuth (Google / Microsoft)

On the **same** OAuth apps (or dev-only apps), add authorized origins / redirect URIs for:

- `http://localhost:5173` (local Vite)
- `https://<dev-ui-host>` (Railway dev UI)

Prod URLs stay on the prod entries only.

---

## Local development workflow

### Backend (`cv-drafter`)

```bash
cd cv-drafter
# .env must use DEV Supabase + dev JWT secrets
uvicorn api.server:app --reload --host 127.0.0.1 --port 8000
```

Copy from `.env.example`. Never commit `.env`.

### Frontend (`cv-drafter-ui`)

```bash
cd cv-drafter-ui
# .env → local API or dev Railway API
npm run dev
```

Default local API:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_AUTH_API_BASE_URL=http://127.0.0.1:8000/auth
```

To hit **hosted dev API** while running Vite locally, set `VITE_API_BASE_URL` to the dev Railway API URL and ensure `CORS_ORIGINS` on dev API includes `http://localhost:5173`.

---

## Quick sanity checks

| Check | Dev | Prod |
|-------|-----|------|
| `GET /health` | Dev API URL | Prod API URL |
| Login | Dev Supabase `app_users` | Prod `app_users` |
| New session + start | Uses dev storage bucket | Prod bucket |
| Credits | Dev `user_meter_balances` | Prod balances |

**Rule:** If you see production session IDs or production user emails while testing a feature branch, your local `.env` is pointing at prod — stop and switch to dev keys.

---

## Deploy flow

```text
feature branch → PR → develop  →  auto-deploy Railway DEV
                              →  test on dev URL + dev Supabase

develop → PR → main  →  auto-deploy Railway PROD (production Supabase)
```

Do not merge to `main` until dev deploy and migrations (if any) are verified.

---

## SQL migrations

- **Dev Supabase:** run new migrations first (SQL Editor or `scripts/run_migrations.py` with dev `DATABASE_URL`).

### `getaddrinfo failed` when running `run_migrations.py`

Windows may not resolve `db.<project-ref>.supabase.co`. Use the **Session pooler** connection string from Supabase → **Database** → **Connection string** (host `aws-0-….pooler.supabase.com`, port `5432`) as `DATABASE_URL` in `.env`, or run SQL files `000`–`003` in the SQL Editor instead.
- **Prod Supabase:** run the same migration after dev is validated — additive scripts only (`CREATE IF NOT EXISTS`, etc.).

See [METERING.md](./METERING.md) for metering tables.

---

## Checklist before first dev deploy

- [ ] Dev Supabase project created
- [ ] Migrations 000 → 001 → 002 → 003 applied on dev
- [ ] Storage bucket `cv-uploads` on dev
- [ ] Railway dev API service → branch `develop`, dev env vars set
- [ ] Railway dev UI service → branch `develop`, `VITE_*` point to dev API
- [ ] `CORS_ORIGINS` on dev API includes dev UI + `http://localhost:5173`
- [ ] OAuth redirect URIs include dev + localhost
- [ ] Local `cv-drafter/.env` uses **dev** Supabase (not prod)
