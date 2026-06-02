alter table public.profiles
add column if not exists preferred_locations text[],
add column if not exists preferred_work_modes text[],
add column if not exists minimum_base_salary integer,
add column if not exists salary_currency text default 'USD';

alter table public.job_matches
add column if not exists match_concerns text[],
add column if not exists interview_likelihood float,
add column if not exists skills_fit float,
add column if not exists experience_fit float,
add column if not exists seniority_fit float,
add column if not exists location_fit float,
add column if not exists pay_fit float,
add column if not exists role_fit float,
add column if not exists preference_fit float,
add column if not exists location_reason text,
add column if not exists location_evidence text,
add column if not exists pay_reason text,
add column if not exists pay_evidence text,
add column if not exists role_reason text,
add column if not exists role_evidence text,
add column if not exists job_facts jsonb;
