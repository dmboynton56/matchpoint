alter table public.job_matches
  add column is_applied boolean not null default false;

create index idx_user_applied on public.job_matches (user_id, is_applied);

create or replace function public.replace_job_matches(
  p_user_id uuid,
  p_matches jsonb
)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  delete from public.job_matches
  where user_id = p_user_id;

  if p_matches is null or jsonb_array_length(p_matches) = 0 then
    return;
  end if;

  insert into public.job_matches (
    user_id,
    job_id,
    match_score,
    match_notes,
    match_highlights,
    match_concerns,
    interview_likelihood,
    skills_fit,
    experience_fit,
    seniority_fit,
    location_fit,
    pay_fit,
    role_fit,
    preference_fit,
    location_reason,
    location_evidence,
    pay_reason,
    pay_evidence,
    role_reason,
    role_evidence,
    job_facts,
    is_viewed,
    is_favorited,
    is_applied
  )
  select
    p_user_id,
    (m->>'job_id')::uuid,
    (m->>'match_score')::double precision,
    m->'match_notes',
    case
      when m->'match_highlights' is null then null
      else array(select jsonb_array_elements_text(m->'match_highlights'))
    end,
    case
      when m->'match_concerns' is null then null
      else array(select jsonb_array_elements_text(m->'match_concerns'))
    end,
    (m->>'interview_likelihood')::double precision,
    (m->>'skills_fit')::double precision,
    (m->>'experience_fit')::double precision,
    (m->>'seniority_fit')::double precision,
    (m->>'location_fit')::double precision,
    (m->>'pay_fit')::double precision,
    (m->>'role_fit')::double precision,
    (m->>'preference_fit')::double precision,
    m->>'location_reason',
    m->>'location_evidence',
    m->>'pay_reason',
    m->>'pay_evidence',
    m->>'role_reason',
    m->>'role_evidence',
    m->'job_facts',
    coalesce((m->>'is_viewed')::boolean, false),
    coalesce((m->>'is_favorited')::boolean, false),
    coalesce((m->>'is_applied')::boolean, false)
  from jsonb_array_elements(p_matches) as m;
end;
$$;

grant execute on function public.replace_job_matches(uuid, jsonb) to service_role;
