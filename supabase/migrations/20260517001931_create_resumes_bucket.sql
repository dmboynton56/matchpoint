-- Create the 'resumes' bucket
INSERT INTO storage.buckets (id, name, public)
VALUES ('resumes', 'resumes', false) -- 'false' keeps resumes private and secure
ON CONFLICT (id) DO NOTHING;

-- Enable Row Level Security (RLS) on the bucket items
-- Allows authenticated users to upload and read their own resumes
CREATE POLICY "Users can upload their own resume" 
ON storage.objects FOR INSERT 
TO authenticated 
WITH CHECK (bucket_id = 'resumes' AND (storage.foldername(name))[1] = auth.uid()::text);

CREATE POLICY "Users can view their own resume" 
ON storage.objects FOR SELECT 
TO authenticated 
USING (bucket_id = 'resumes' AND (storage.foldername(name))[1] = auth.uid()::text);