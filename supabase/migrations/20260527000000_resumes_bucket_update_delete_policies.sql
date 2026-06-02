-- Resume bucket policies: allow users to manage only their own objects.
-- The object key is expected to be stored under: <auth.uid()>/<filename>

CREATE POLICY "Users can update their own resume"
ON storage.objects
FOR UPDATE
TO authenticated
USING (
  bucket_id = 'resumes'
  AND (storage.foldername(name))[1] = auth.uid()::text
)
WITH CHECK (
  bucket_id = 'resumes'
  AND (storage.foldername(name))[1] = auth.uid()::text
);

CREATE POLICY "Users can delete their own resume"
ON storage.objects
FOR DELETE
TO authenticated
USING (
  bucket_id = 'resumes'
  AND (storage.foldername(name))[1] = auth.uid()::text
);
