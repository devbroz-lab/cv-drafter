-- Align sessions.user_id with app auth (public.app_users).
-- The API uses app_users for JWT "sub"; legacy FK to public.users causes 23503 on POST /sessions.
--
-- Safe for new projects: drops only the FK, does not truncate sessions.
-- If ADD CONSTRAINT fails, you have session rows whose user_id is not in app_users (run the
-- orphan check query in a comment below, then fix or delete those rows as appropriate).

ALTER TABLE public.sessions
  DROP CONSTRAINT IF EXISTS sessions_user_id_fkey;

ALTER TABLE public.sessions
  ADD CONSTRAINT sessions_user_id_fkey
  FOREIGN KEY (user_id)
  REFERENCES public.app_users (id)
  ON DELETE CASCADE;

-- Orphan check (run before re-adding FK if needed):
-- SELECT s.id, s.user_id
-- FROM public.sessions s
-- LEFT JOIN public.app_users a ON a.id = s.user_id
-- WHERE a.id IS NULL;
