-- Update default for public.jobs
ALTER TABLE public.jobs 
ALTER COLUMN created_at SET DEFAULT now();

-- Update default for public.job_matches
ALTER TABLE public.job_matches 
ALTER COLUMN created_at SET DEFAULT now();