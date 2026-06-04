-- Base pipeline table (run first on a new Supabase project).
-- Later migrations: 001 app auth, 002 repoint user_id → app_users, 003 metering.

create extension if not exists pgcrypto;

create table if not exists public.sessions (
  id                  uuid primary key default gen_random_uuid(),
  user_id             uuid references auth.users(id) on delete cascade,

  status              text not null default 'queued',
  target_format       text not null check (target_format in ('giz', 'world_bank')),

  source_filename     text not null,
  tor_filename        text,
  output_file_path    text,
  error_message       text,

  source_storage_key  text,
  tor_storage_key     text,
  output_storage_key  text,

  page_limit          integer,
  round               integer default 1,

  tor_text            text,
  job_description     text default '',
  recruiter_comments  text default '',

  proposed_position   text,
  category            text,
  employer            text,
  years_with_firm     text,

  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),

  constraint sessions_status_check check (
    status in (
      'queued',
      'processing',
      'checkpoint_1_pending',
      'checkpoint_2_pending',
      'reviewer_blocked',
      'field_editor_pending',
      'checkpoint_3_pending',
      'completed',
      'failed'
    )
  )
);

-- updated_at trigger
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists trg_sessions_updated_at on public.sessions;
create trigger trg_sessions_updated_at
before update on public.sessions
for each row execute function public.set_updated_at();

-- indexes
create index if not exists idx_sessions_user_id on public.sessions(user_id);
create index if not exists idx_sessions_user_status on public.sessions(user_id, status);
