# Credit metering (Tailor-it)

Parametrised credit system for pipeline runs and post-completion revisions. Rates are configured via environment variables; business logic reads them through `api/services/metering/engine.py`.

## Product rules

| Event | Default USD | Default credits (1 credit = $1) |
|--------|-------------|----------------------------------|
| Full pipeline run | $2.00 | 2 |
| Field revision (`POST /field-edit`) | $0.20 | 0.2 |
| New user grant | — | 20 |

**Not metered:** session create, uploads, checkpoints, downloads, viewing output.

## Configuration

Add to `cv-drafter/.env` (see `.env.example`):

```env
METER_CREDIT_USD=1.0
METER_PIPELINE_RUN_USD=2.0
METER_REVISION_USD=0.20
METER_INITIAL_GRANT_CREDITS=20
```

Change only these values when pricing changes — no code edits required.

## Database setup

**Recommended (script, additive-only):**

```bash
cd cv-drafter
# Add SUPABASE_DB_PASSWORD or DATABASE_URL to .env (Supabase → Settings → Database)
pip install "psycopg[binary]>=3.2"
python scripts/run_migrations.py --dry-run
python scripts/run_migrations.py
```

If auth migrations were already applied manually, mark them without re-running:

```bash
python scripts/run_migrations.py --mark-applied 001_create_app_auth_tables --mark-applied 002_sessions_user_fk_app_users
python scripts/run_migrations.py --only 003_metering
```

**Manual alternative:** run `api/migrations/003_metering_tables.sql` in the Supabase SQL editor.

Tables:

- `user_meter_balances` — `available_credits`, `reserved_credits`
- `meter_ledger` — audit trail with `idempotency_key`
- `session_metering` — per-session reserve/commit flags

### Existing users

On first `GET /metering/balance` or `GET /auth/me`, `provision_new_user()` grants the initial credits once (idempotent key `grant:{user_id}`).

To backfill manually:

```sql
-- Example: ensure balance row exists; grant is handled by the API on next login.
INSERT INTO user_meter_balances (user_id, available_credits, reserved_credits)
SELECT id, 0, 0 FROM app_users
ON CONFLICT (user_id) DO NOTHING;
```

Then have each user hit `/metering/balance` once, or run an admin script that calls `provision_new_user` per user.

## Billing flow

### Pipeline (reserve → commit / release)

1. **`POST /sessions/{id}/start`** — reserves `pipeline_run_credits` from available → reserved. Returns **402** if insufficient.
2. **`set_done()`** (first successful render to `completed`) — commits reserve (deducts from reserved permanently).
3. **`set_failed()`** or startup stale recovery — releases reserve back to available.

Re-renders after revision (`round > 1`) do not charge pipeline again.

### Revision (immediate debit)

1. **`POST /sessions/{id}/field-edit`** — debits `revision_credits` before `increment_round` / field editor.
2. On hard failure — **refunds** the debit for that round (`revision_refund`).

Idempotency keys: `pipeline_reserve:{session_id}`, `pipeline_commit:{session_id}`, `revision:{session_id}:{round}`.

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/metering/balance` | Available, reserved, total, current rates |
| `GET` | `/metering/ledger?limit=50` | Usage history |
| `GET` | `/auth/me` | Includes `metering` + `rates` for app users |

### 402 Payment Required

```json
{
  "detail": {
    "message": "Insufficient credits",
    "required_credits": "2.0000",
    "available_credits": "1.2000",
    "event": "pipeline_run"
  }
}
```

## Code layout

```
api/services/metering/
  engine.py    # USD → credits, rates snapshot
  service.py   # DB: reserve, commit, release, debit, grant
  http.py      # 402 helper
api/routers/metering.py
```

Integration points:

- `api/routers/sessions.py` — `start`, `field-edit`
- `api/services/database.py` — `set_done`, `set_failed`, `create_app_user`, stale recovery
- `api/routers/auth.py` — `GET /me` balance

## Frontend

- `src/lib/metering.ts` — types, `fetchMeterBalance`, `fetchMeterLedger`
- `src/components/CreditBalance.tsx` — sidebar pill
- `NewSessionPage` — cost hint, disable when insufficient
- `SessionWorkspacePage` / `DocxViewer` — revision cost on apply
- `SettingsPage` — balance, rates, ledger

React Query key: `["metering", "balance"]` — invalidate after start and field-edit.

## Tests

```bash
cd cv-drafter
python -m pytest tests/test_metering_engine.py -q
```

## Future work

- Admin `POST /metering/grant` for top-ups
- Stripe / billing provider integration
- Per-organization pools
