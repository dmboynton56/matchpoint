-- Paste this into the Supabase SQL editor once before enabling durable
-- favorites/applied jobs in shared environments.

create table if not exists public.user_saved_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  job_id text not null,
  source_match_id uuid,
  is_favorited boolean not null default false,
  is_applied boolean not null default false,
  favorited_at timestamptz,
  applied_at timestamptz,
  updated_at timestamptz not null default now(),
  latest_match_score double precision,
  job_snapshot jsonb not null default '{}'::jsonb,
  match_snapshot jsonb not null default '{}'::jsonb,
  constraint user_saved_jobs_user_job_unique unique (user_id, job_id),
  constraint user_saved_jobs_has_state check (is_favorited or is_applied)
);

create index if not exists idx_user_saved_jobs_user_favorited
  on public.user_saved_jobs (user_id, is_favorited);

create index if not exists idx_user_saved_jobs_user_applied
  on public.user_saved_jobs (user_id, is_applied);

alter table public.user_saved_jobs enable row level security;

drop policy if exists "Users can read their saved jobs"
  on public.user_saved_jobs;
create policy "Users can read their saved jobs"
  on public.user_saved_jobs for select
  using (auth.uid() = user_id);

drop policy if exists "Users can insert their saved jobs"
  on public.user_saved_jobs;
create policy "Users can insert their saved jobs"
  on public.user_saved_jobs for insert
  with check (auth.uid() = user_id);

drop policy if exists "Users can update their saved jobs"
  on public.user_saved_jobs;
create policy "Users can update their saved jobs"
  on public.user_saved_jobs for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

drop policy if exists "Users can delete their saved jobs"
  on public.user_saved_jobs;
create policy "Users can delete their saved jobs"
  on public.user_saved_jobs for delete
  using (auth.uid() = user_id);
