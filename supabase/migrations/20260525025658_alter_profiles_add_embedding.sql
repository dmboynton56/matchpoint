-- Store resume vector for similarity search against jobs.embedding
ALTER TABLE public.profiles
  ADD COLUMN resume_embedding vector(1536);

COMMENT ON COLUMN public.profiles.resume_embedding IS
  'OpenAI text-embedding-3-small (1536) of resume_text for job matching';