-- 006_files_storage_metadata.sql
-- Purpose: Add storage metadata columns to public.files and backfill existing rows.
-- Columns:
--   - storage_key text: logical key "{file_id}{ext}"; adapters may add their own prefixes/paths.
--   - size_bytes bigint: object size in bytes; may be corrected by adapters on next access.
--   - storage_backend text: identifier of the storage backend (e.g., 'local', 'supabase').
-- Notes:
--   - Backfill derives ext as '.pdf' or '.txt' from mime/filename, else ''.
--   - Backfill uses storage_key := COALESCE(existing, id::text || ext).
--   - Backfill uses size_bytes := COALESCE(existing, 0) and storage_backend := COALESCE(existing, 'local').
--   - Check constraint ensures size_bytes is NULL or non-negative.

BEGIN;

-- 1) Add columns (idempotent)
ALTER TABLE IF EXISTS public.files
  ADD COLUMN IF NOT EXISTS storage_key text,
  ADD COLUMN IF NOT EXISTS size_bytes bigint,
  ADD COLUMN IF NOT EXISTS storage_backend text;

-- 2) Backfill using derived extension from mime/filename
WITH derived AS (
  SELECT
    id,
    CASE
      WHEN mime ILIKE 'application/pdf' OR filename ILIKE '%.pdf' THEN '.pdf'
      WHEN mime ILIKE 'text/plain' OR filename ILIKE '%.txt' THEN '.txt'
      ELSE ''
    END AS ext
  FROM public.files
)
UPDATE public.files f
SET
  storage_key = COALESCE(f.storage_key, f.id::text || d.ext),
  size_bytes = COALESCE(f.size_bytes, 0),
  storage_backend = COALESCE(f.storage_backend, 'local')
FROM derived d
WHERE f.id = d.id;

-- 3) Add non-negative size check constraint if missing
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'files_size_bytes_nonneg'
      AND conrelid = 'public.files'::regclass
  ) THEN
    ALTER TABLE public.files
      ADD CONSTRAINT files_size_bytes_nonneg CHECK (size_bytes IS NULL OR size_bytes >= 0);
  END IF;
END $$;

-- 4) Optional column comments for clarity
COMMENT ON COLUMN public.files.storage_key IS 'Logical key "{file_id}{ext}"; adapters may add prefixes/paths internally';
COMMENT ON COLUMN public.files.size_bytes IS 'Size in bytes (may be 0 for legacy rows and corrected by adapters later)';
COMMENT ON COLUMN public.files.storage_backend IS 'Storage backend identifier (e.g., local, supabase)';

COMMIT;

-- Acceptance (manual):
-- SELECT storage_key,size_bytes,storage_backend FROM public.files LIMIT 5;
