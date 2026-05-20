-- PROFILES: Extends the local Supabase Auth
CREATE TABLE public.profiles (
  id UUID REFERENCES auth.users NOT NULL PRIMARY KEY,
  full_name TEXT,
  resume_text TEXT, -- For the MVP, we store the parsed text here [cite: 231]
  target_role TEXT,
  created_at timestamptz DEFAULT now() NOT NULL
);
