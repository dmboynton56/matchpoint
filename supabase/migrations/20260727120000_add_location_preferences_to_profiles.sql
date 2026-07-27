-- Migration: structured location preferences on profiles
--
-- These columns back the geolocation hard-filter in the matching route.
-- The contract: a profile with no fields populated (the default for
-- existing users) is treated as "no preference" and the route does not
-- filter anything out. Default values are chosen so that adding these
-- columns to a table that already has data is a true no-op for existing
-- rows.
--
-- Run this migration on the Supabase project BEFORE deploying the
-- matching-route change. The route's soft-fail on missing columns
-- (see _is_missing_preference_columns_error in routes/resumes.py) keeps
-- the system running if the migration lands after the code, but the
-- filter won't engage until both are present.

alter table public.profiles
  add column if not exists location_mode text default 'country',
  add column if not exists preferred_country_codes text[] default '{}',
  add column if not exists preferred_city text,
  add column if not exists preferred_lat double precision,
  add column if not exists preferred_lon double precision,
  add column if not exists preferred_radius_km integer,
  add column if not exists preferred_regions text[] default '{}',
  add column if not exists target_seniority text[] default '{internship,entry,mid}';

-- Index for the new column. The matching route uses
--   WHERE experience_level = ANY(target_seniority)
-- which can use a btree on a text[] column via GIN.
create index if not exists idx_profiles_target_seniority
  on public.profiles using gin (target_seniority);

-- Index lets the read path filter by country set cheaply. Small
-- (country codes are 2 bytes) and high-cardinality, so btree is fine.
create index if not exists idx_profiles_preferred_country_codes
  on public.profiles using gin (preferred_country_codes);
