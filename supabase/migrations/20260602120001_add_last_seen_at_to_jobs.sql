ALTER TABLE public.jobs
ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP WITH TIME ZONE
DEFAULT timezone('utc'::text, now());

UPDATE public.jobs
SET last_seen_at = created_at
WHERE last_seen_at IS NULL;