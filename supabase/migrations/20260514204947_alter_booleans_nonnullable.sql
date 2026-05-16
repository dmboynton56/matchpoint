-- Update booleans for public.job_matches to be non-nullable
ALTER TABLE public.job_matches 
  ALTER COLUMN is_viewed SET NOT NULL,
  ALTER COLUMN is_favorited SET NOT NULL;