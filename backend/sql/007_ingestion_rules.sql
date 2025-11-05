-- 007_ingestion_rules.sql
ALTER TABLE public.files
  ADD COLUMN IF NOT EXISTS needs_ocr boolean DEFAULT false NOT NULL,
  ADD COLUMN IF NOT EXISTS ingestion_failed text CHECK (ingestion_failed IN ('size_cap','ocr_required','other')) NULL,
  ADD COLUMN IF NOT EXISTS processed_at timestamptz NULL;

CREATE INDEX IF NOT EXISTS idx_files_sha256 ON public.files(sha256);