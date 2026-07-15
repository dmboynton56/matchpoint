-- Backend uses the Supabase service_role key for all Postgres access.
-- Local Supabase (and some hosted resets) do not inherit table grants on
-- app-owned tables created via migrations, which surfaces as:
--   permission denied for table profiles / job_matches (42501)

grant usage on schema public to service_role;

grant select, insert, update, delete on table public.profiles to service_role;
grant select, insert, update, delete on table public.job_matches to service_role;
grant select, insert, update, delete on table public.resume_suggestions to service_role;

-- Legacy / optional — harmless if the table was never created locally.
grant select, insert, update, delete on table public.jobs to service_role;

do $$
begin
  if to_regclass('public.user_saved_jobs') is not null then
    grant select, insert, update, delete on table public.user_saved_jobs to service_role;
  end if;
end
$$;
