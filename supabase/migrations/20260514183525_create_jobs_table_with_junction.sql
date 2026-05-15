-- Enable the pgvector extension for AI similarity search
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE public.jobs (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY, -- Internal id
  external_id TEXT UNIQUE, -- From web scraping
  company TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  location TEXT,
  posted_at TIMESTAMP WITH TIME ZONE,
  apply_url TEXT,
  
  -- Vector column for OpenAI text-embedding-3-small (1536 dimensions)
  embedding vector(1536), 
  
  created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- The Match Junction Table: Able to reference many users for a single job
CREATE TABLE public.job_matches (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  job_id UUID REFERENCES public.jobs(id) ON DELETE CASCADE NOT NULL,
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
  is_viewed BOOLEAN DEFAULT FALSE,
  is_favorited BOOLEAN DEFAULT FALSE,
  
  -- Store AI-calculated score here for easy display
  match_score FLOAT, 
  
  UNIQUE(job_id, user_id), -- Prevents duplicate matches
  created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Indices for Performance
CREATE INDEX ON public.jobs USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100); -- Optimization for fast similarity search
-- Thiscomposite index handles: WHERE user_id = '...' AND is_favorited = true
CREATE INDEX idx_user_favorites ON public.job_matches (user_id, is_favorited);