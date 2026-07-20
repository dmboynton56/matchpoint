-- Auto-create a public.profiles row whenever a new auth.users row is
-- inserted, so downstream code (frontend preferences, backend
-- _fetch_resume_text, the suggestions flow, etc.) can rely on the
-- row existing for every authenticated user.
--
-- Why this exists
-- ----------------
-- Before this migration, profiles were created only when something
-- explicitly wrote to the table. The backend's resume upload path
-- (handle_authenticated_upload) used PostgREST's .update().eq(),
-- which silently affects 0 rows when the row doesn't exist yet --
-- so a brand-new account could complete a full resume upload
-- (matches, embeddings, the works) and still have no profiles row,
-- because the update was a no-op. The next /suggestions/refresh
-- call would then 404 on _fetch_resume_text. The handle_authenticated_
-- upload path now upserts as belt-and-suspenders, but the trigger
-- is the architectural fix: it removes the class of bug rather
-- than one instance.
--
-- Idempotency
-- -----------
-- CREATE OR REPLACE FUNCTION + DROP TRIGGER IF EXISTS make this safe
-- to re-run during local resets. ON CONFLICT (id) DO NOTHING makes
-- the function safe to call repeatedly for the same user -- the
-- handle_authenticated_upload upsert (which inserts the resume_text
-- + resume_embedding right after signup) and this trigger can race
-- in either order without duplicating rows.
--
-- Backfill
-- --------
-- Existing accounts that signed up before this migration will not
-- have a profile row from this trigger. Their next resume upload
-- will create one via the upsert in handle_authenticated_upload.
-- No separate backfill step is needed.

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, full_name)
  values (
    new.id,
    -- Supabase auth stores user metadata in raw_user_meta_data.
    -- Prefer the explicit full_name key (used by some signup flows),
    -- then fall back to `name` (OAuth providers often set this).
    -- Either way, leaving it null is fine -- the user can fill it
    -- in later via the preferences form.
    coalesce(
      new.raw_user_meta_data ->> 'full_name',
      new.raw_user_meta_data ->> 'name'
    )
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

-- Trigger fires AFTER INSERT so the auth.users row is fully written
-- before the profile row references it. The function is idempotent
-- (ON CONFLICT DO NOTHING) so re-creating the trigger and replaying
-- the auth.users insert is safe.
drop trigger if exists on_auth_user_created on auth.users;

create trigger on_auth_user_created
  after insert on auth.users
  for each row
  execute function public.handle_new_user();
