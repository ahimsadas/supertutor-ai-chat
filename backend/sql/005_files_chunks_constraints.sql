-- Enforce & consolidate files/chunks constraints and indexes (idempotent)
BEGIN;

-- A) Pre-clean: remove orphan chunks (safe to auto-fix)
WITH orphan_chunks AS (
  SELECT c.id
  FROM public.chunks c
  LEFT JOIN public.files f ON f.id = c.file_id
  WHERE f.id IS NULL
)
DELETE FROM public.chunks
WHERE id IN (SELECT id FROM orphan_chunks);

-- B) Pre-check: any files pointing to missing curricula? Abort to avoid creating invalid FK.
DO $$
DECLARE v_count bigint;
BEGIN
  SELECT COUNT(*) INTO v_count
  FROM public.files f
  LEFT JOIN public.curricula cu ON cu.id = f.curriculum_id
  WHERE cu.id IS NULL;
  IF v_count > 0 THEN
    RAISE EXCEPTION 'Migration aborted: % file(s) reference missing curricula. Clean these rows before re-running.', v_count;
  END IF;
END $$ LANGUAGE plpgsql;

-- C) Ensure composite unique on (curriculum_id, sha256) (drop single-column unique if present)
ALTER TABLE public.files
  DROP CONSTRAINT IF EXISTS files_sha256_key;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'public.files'::regclass
      AND conname = 'files_curriculum_sha256_key'
  ) THEN
    ALTER TABLE public.files
      ADD CONSTRAINT files_curriculum_sha256_key UNIQUE (curriculum_id, sha256);
  END IF;
END $$ LANGUAGE plpgsql;

-- D) Ensure files.curriculum_id FK is RESTRICT/NO ACTION (drop & re-add only if needed)
DO $$
BEGIN
  PERFORM 1
  FROM pg_constraint
  WHERE conrelid = 'public.files'::regclass
    AND conname = 'files_curriculum_id_fkey'
    AND confdeltype IN ('r','a'); -- 'r' RESTRICT, 'a' NO ACTION

  IF NOT FOUND THEN
    IF EXISTS (
      SELECT 1 FROM pg_constraint
      WHERE conrelid = 'public.files'::regclass
        AND conname = 'files_curriculum_id_fkey'
    ) THEN
      ALTER TABLE public.files DROP CONSTRAINT files_curriculum_id_fkey;
    END IF;
    ALTER TABLE public.files
      ADD CONSTRAINT files_curriculum_id_fkey
      FOREIGN KEY (curriculum_id) REFERENCES public.curricula(id) ON DELETE RESTRICT;
  END IF;
END $$ LANGUAGE plpgsql;

-- E) Ensure chunks.file_id FK has ON DELETE CASCADE (drop & re-add only if needed)
DO $$
BEGIN
  PERFORM 1
  FROM pg_constraint
  WHERE conrelid = 'public.chunks'::regclass
    AND conname = 'chunks_file_id_fkey'
    AND confdeltype = 'c'; -- 'c' CASCADE

  IF NOT FOUND THEN
    IF EXISTS (
      SELECT 1 FROM pg_constraint
      WHERE conrelid = 'public.chunks'::regclass
        AND conname = 'chunks_file_id_fkey'
    ) THEN
      ALTER TABLE public.chunks DROP CONSTRAINT chunks_file_id_fkey;
    END IF;
    ALTER TABLE public.chunks
      ADD CONSTRAINT chunks_file_id_fkey
      FOREIGN KEY (file_id) REFERENCES public.files(id) ON DELETE CASCADE;
  END IF;
END $$ LANGUAGE plpgsql;

-- Helpful index for joins/cascade scans (also defined in base schema; safe to re-assert)
CREATE INDEX IF NOT EXISTS idx_chunks_file_id ON public.chunks(file_id);

COMMIT;
