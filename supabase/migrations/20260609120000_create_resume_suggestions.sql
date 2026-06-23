-- Resume improvement suggestions
-- One row per generation; history preserved across uploads.
-- cache_key is sha256(resume_text || ','.join(sorted(top_20_job_ids)))
-- so we can cheaply answer "do I have suggestions for the current state?".

create table if not exists public.resume_suggestions (
  id uuid default gen_random_uuid() primary key,
  user_id uuid references auth.users(id) on delete cascade not null,
  cache_key text not null,
  created_at timestamptz default now() not null,
  suggestions jsonb not null
);

-- Lookup: latest matching row for a (user, cache_key).
create index if not exists idx_resume_suggestions_user_cache
  on public.resume_suggestions (user_id, cache_key, created_at desc);

-- List newest-first when showing history.
create index if not exists idx_resume_suggestions_user_created
  on public.resume_suggestions (user_id, created_at desc);

-- Row Level Security: users only see their own rows.
alter table public.resume_suggestions enable row level security;

create policy "Users can view own resume suggestions"
  on public.resume_suggestions
  for select
  to authenticated
  using (id = auth.uid() or user_id = auth.uid());

create policy "Users can insert own resume suggestions"
  on public.resume_suggestions
  for insert
  to authenticated
  with check (user_id = auth.uid());

create policy "Users can delete own resume suggestions"
  on public.resume_suggestions
  for delete
  to authenticated
  using (user_id = auth.uid());
