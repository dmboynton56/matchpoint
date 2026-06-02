alter table public.job_matches
add column if not exists match_notes jsonb;
