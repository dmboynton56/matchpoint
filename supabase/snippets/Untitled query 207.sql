SELECT *
FROM jobs 
WHERE created_at::date = CURRENT_DATE;