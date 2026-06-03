-- Credit / metering tables (additive; safe for existing pipeline data).

CREATE TABLE IF NOT EXISTS public.user_meter_balances (
  user_id UUID PRIMARY KEY REFERENCES public.app_users(id) ON DELETE CASCADE,
  available_credits NUMERIC(12, 4) NOT NULL DEFAULT 0 CHECK (available_credits >= 0),
  reserved_credits NUMERIC(12, 4) NOT NULL DEFAULT 0 CHECK (reserved_credits >= 0),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.meter_ledger (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES public.app_users(id) ON DELETE CASCADE,
  session_id UUID,
  event_type VARCHAR(32) NOT NULL,
  amount_credits NUMERIC(12, 4) NOT NULL,
  usd_rate_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  idempotency_key VARCHAR(255) NOT NULL UNIQUE,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_meter_ledger_user_id_created
  ON public.meter_ledger(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_meter_ledger_session_id
  ON public.meter_ledger(session_id);

CREATE TABLE IF NOT EXISTS public.session_metering (
  session_id UUID PRIMARY KEY,
  pipeline_reserved BOOLEAN NOT NULL DEFAULT FALSE,
  pipeline_committed BOOLEAN NOT NULL DEFAULT FALSE,
  revision_count INT NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
