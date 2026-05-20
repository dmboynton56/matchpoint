create or replace function match_jobs(
  query_embedding vector(1536),
  match_limit int
)
returns table (
  id uuid,
  title text,
  company text,
  location text,
  apply_url text,
  similarity float
)
language sql stable
as $$
  select
    id, title, company, location, apply_url,
    1 - (embedding <=> query_embedding) as similarity
  from jobs
  where embedding is not null
  order by embedding <=> query_embedding
  limit match_limit;
$$;