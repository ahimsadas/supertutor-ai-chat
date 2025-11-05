# SuperTutor AI Chat

An AI RAG chatbot MVP using LangChain with Supabase pgvector, supporting multi-provider LLM switching, citations, and a React UI.

## Monorepo layout
- `backend/` — FastAPI backend with Supabase (providers, languages, curricula endpoints)
- `frontend/` — React frontend (to be implemented)

## MVP scope
Student-facing frontend and an admin CLI for data ingestion. No authentication yet.

## Next steps
- [ ] Define MVP backlog
- [ ] Choose initial LLM provider(s)
- [ ] Set up ingestion pipeline outline
- [ ] Establish development environment and tooling

## Supabase setup (Step 2)

- Create a Supabase project in the console and copy:
  - Project URL
  - anon key
  - service_role key
  - a Postgres connection string (session or transaction mode)
- Paste them later into `backend/.env` (not committed), following `backend/.env.example`.
- The `service_role` key is server-only and bypasses RLS; never expose it on the client side.

## Enable pgvector (Step 3)

- Two activation paths:
  - (a) Studio: Database → Extensions → enable "vector"
  - (b) SQL: run `create extension if not exists vector;`
- Verification query: `select extname from pg_extension where extname = 'vector';`
- Run this once per Supabase project/database.

## Create core DB tables (Step 4)

- Open Supabase Studio → Database → SQL Editor.
- Paste and run the contents of `backend/sql/002_schema_core.sql`.
- Verify:
  - Tables exist:
    ```sql
    select table_name
    from information_schema.tables
    where table_schema = 'public'
      and table_name in ('curricula','files','chunks','threads','messages')
    order by table_name;
    ```
  - `chunks.embedding` type is `vector(1536)`:
    ```sql
    select format_type(a.atttypid, a.atttypmod) as embedding_type
    from pg_attribute a
    join pg_class c on c.oid = a.attrelid
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public' and c.relname = 'chunks' and a.attname = 'embedding';
    ```
  - `messages.citations` type is `jsonb`:
    ```sql
    select data_type
    from information_schema.columns
    where table_schema = 'public' and table_name = 'messages' and column_name = 'citations';
    ```
 - Note: This step does not run automatically; execute it manually in Studio (or `psql`).
 - Languages are registry-defined in code (see `backend/app/languages/registry.py`). No languages table or migration is required.

## Add HNSW index (Step 5)

- Open Supabase Studio → Database → SQL Editor.
- Paste and run the contents of `backend/sql/003_index_hnsw.sql`.
- Verify the index exists:
  ```sql
  select indexname, indexdef
  from pg_indexes
  where schemaname = 'public' and tablename = 'chunks';
  ```
- Optional tuning (session-level):
  ```sql
  set hnsw.ef_search = 100; -- or use SET LOCAL inside a transaction
  ```
- Query note: cosine distance uses the `<=>` operator in pgvector.

## Step 6: RPC match_documents (vector search + JSONB filtering)

- Open Supabase Studio → Database → SQL Editor.
- Paste and run the contents of `backend/sql/004_rpc_match_documents.sql`.
- Smoke tests:
  - No filter:
    ```sql
    select *
    from public.match_documents(
      (select embedding from public.chunks limit 1),
      5,
      '{}'::jsonb
    );
    ```
  - Filter by curriculum:
    ```sql
    select *
    from public.match_documents(
      (select embedding from public.chunks limit 1),
      5,
      jsonb_build_object('curriculum_id','<uuid>')
    );
    ```
- Optional tuning: set a higher `hnsw.ef_search` for better recall (per session):
  ```sql
  set hnsw.ef_search = 100; -- adjust as needed
  ```

## Backend (Step 7)

- Create and activate a virtual environment, then install dependencies:
  ```bash
  cd backend
  python -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt
  ```
- Run the API locally:
  ```bash
  uvicorn app.main:app --reload --port 8000
  ```
- Verify health endpoint:
  ```bash
  curl -s http://localhost:8000/healthz
  # {"ok": true, "service": "supertutor-backend"}
  ```
 - Notes:
  - Config auto-loads from `backend/.env` for both the FastAPI server and all CLI entrypoints (via pydantic-settings). You do not need to export variables in your shell.
  - OpenAI API key is required when running the ingestion job runner to generate embeddings (model `text-embedding-3-small`). Set `OPENAI_API_KEY` in `backend/.env`. Other provider keys (Anthropic/Google/DeepSeek/xAI) remain optional for later steps.
  - Supabase server-only variables `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are required only when you actually request a Supabase client in code.
  - Upload/ingestion caps:
    - `FILES_UPLOAD_MAX_MB` (float | empty) — optional router/HTTP preflight cap. Leave empty for no router cap.
    - `FILES_INGEST_MAX_MB` (float) — runner/ingestion cap. Files over this are marked `ingestion_failed='size_cap'` and skipped by the runner.
  - Embeddings:
    - `EMBEDDING_MODEL` (default `text-embedding-3-small`)
    - `EMBEDDING_BATCH_SIZE` (default `64`)
    - `EMBEDDING_DIM` (default `1536`)

### Languages (registry-based)

- The available languages are defined in code at `backend/app/languages/registry.py`.
- The API `GET /languages` returns this static, read-only list (enabled entries only), ordered by `sort_order` then `name`.
- No database seeding or CRUD exists for languages; there is no `public.languages` table.

### Admin CLI: Curricula

- A minimal Typer-based CLI is available to manage curricula via the REST API.
- Module: `backend/app/cli/curricula.py` (run with `python -m app.cli.curricula ...` from `backend/`).
- Base URL comes from settings `BACKEND_BASE_URL` (in `backend/.env`, default `http://localhost:8000`).

Examples:

```bash
# List curricula
python -m app.cli.curricula list

# Create a curriculum
python -m app.cli.curricula create --name "JEE Physics"

# Delete a curriculum by id
python -m app.cli.curricula delete --id <uuid>
```

The JSON summary includes an `inserted` total row count across processed files.

Exit codes:

- `list`: 0 on success; 1 on HTTP errors.
- `create`: 0 on 200/201; 2 on 409 duplicate; 1 on other errors.
- `delete`: 0 on 200/204; 3 on 404 not found; 4 on 409 forbidden delete; 1 on other errors.


### Admin CLI: Ingestion

- A Typer-based CLI to upload source documents to the backend ingestion route.
- Module: `backend/app/cli/ingest.py` (run with `python -m app.cli.ingest ...` from `backend/`).
- Base URL comes from settings `BACKEND_BASE_URL` (in `backend/.env`, default `http://localhost:8000`).
- Optional local preflight cap mirrors the router cap via `FILES_UPLOAD_MAX_MB` (float). Leave empty to disable CLI preflight.

Examples:

```bash
# Upload one or more files to a curriculum
python -m app.cli.ingest upload --curriculum-id <uuid> ./samples/a.pdf ./samples/b.txt

# With a smaller local cap (100KB) using the router-aligned setting
FILES_UPLOAD_MAX_MB=0.1 python -m app.cli.ingest upload --curriculum-id <uuid> ./samples/a.pdf
```

Behavior:

- Only .pdf and .txt are accepted by the CLI and server.
- The CLI streams and prints each file's sha256 before sending.
- On server success, prints the JSON response (including `deduped` and `ingestion_status`).
- Global storage dedupe at ingest: when any existing file in any curriculum shares the same `sha256`, the server reuses its `storage_key` (no re-upload) and returns `clone_from_file_id`; if all accepted files reused storage, `ingestion_status` will be `"clone-from"`.
- If the server path is missing, prints a helpful 404 message.


### Admin CLI: Files

- Manage files via backend endpoints.
- Module: `backend/app/cli/files.py` (run with `python -m app.cli.files ...` from `backend/`).
- Base URL is read from env `BACKEND_BASE_URL` (default `http://localhost:8000`).

Examples:

```bash
# List files for a curriculum
python -m app.cli.files list --curriculum-id <uuid>

# Delete a file by id (will cascade-delete its chunks)
python -m app.cli.files delete --id <uuid>
```

Exit codes:

- `list`: 0 on 200; 1 on 404 (curriculum not found); 3 on other errors / network.
- `delete`: 0 on 200; 1 on 404 (file not found); 2 on 409 conflict; 3 on other errors / network.

### Ingestion Job Runner

- Scans recent files (or a specific file) and runs the pipeline: load (PDF/TXT) → chunk → embed → persist.
- Blobs are fetched from Supabase Storage using the file's `storage_key`; no local filesystem storage is used.
- Chunking produces page-relative chunks for embeddings with fields: `{file_id, page, start_index, snippet}`.
- Embeddings: batches snippets with OpenAI `text-embedding-3-small` (1536-d). Default batch size: 64. Requires `OPENAI_API_KEY`.
- Persistence: inserts rows into `public.chunks` with `embedding vector(1536)`; updates `files.pages` if the DB value is `NULL`.
- Idempotent: if any rows already exist in `public.chunks` for a file, the runner skips re-inserting.
- Optional env overrides: `CHUNK_SIZE_CHARS` (default 500), `CHUNK_OVERLAP_CHARS` (default 60).

Rule enforcement:

- Dedupe: for files with identical `sha256`, chunks are cloned from an existing source (no re-embedding).
- OCR triage: likely scanned PDFs are marked `needs_ocr=true` and skipped.
- Size cap: files exceeding `FILES_INGEST_MAX_MB` are marked `ingestion_failed='size_cap'` and skipped.

CLI usage:

```bash
# Dry-run: list/validate without processing
python -m app.cli.ingestion_jobs run --limit 5 --dry-run

# Process a specific file (skips if chunks already exist)
python -m app.cli.ingestion_jobs run --file-id <uuid>

# Filter by curriculum and scan up to 20 recent files
python -m app.cli.ingestion_jobs run --curriculum-id <uuid> --limit 20
```

Verification:

```sql
-- Verify rows were inserted for a specific file
select count(*) from public.chunks where file_id = '<uuid>';

-- Spot-check a few persisted snippets and vector dims
select file_id, page, start_index, left(snippet, 80) as snippet_preview,
       cardinality(embedding) as dim
from public.chunks
where file_id = '<uuid>'
limit 5;
```

Exit codes:

- 0: success and no errors in summary
- 1: invalid inputs, runner-level error, or one/more items had `errors > 0`

### Loading Layer

- Reads file blobs from Supabase Storage and returns per-page text for downstream processing.
- Entrypoint: `app.ingestion.loader.load_from_storage(file_id, storage_key, mime)`.
- PDFs use `UnstructuredPDFLoader(mode="elements")`; TXTs are UTF-8 single-page.

### Supabase Storage

- Bucket is picked from env `SUPABASE_FILES_BUCKET` (default `files`).
- On first use, the backend ensures the bucket exists. With a service role key it will attempt to auto-create a private bucket if missing; otherwise it raises a clear error instructing you to create the bucket or set the env.
- Object keys are stored as `files/{uuid}{ext}`.

### Files storage metadata (DB)

- Columns on `public.files`: `storage_key` (text), `size_bytes` (bigint), `storage_backend` (text).
- `storage_key` is the logical key `{uuid}{ext}` with a `files/` prefix in Supabase (e.g., `files/{uuid}.pdf`).
- Legacy rows are backfilled with `storage_key = id || ext` (ext from mime/filename, `.pdf`/`.txt` else empty), `size_bytes = 0`, `storage_backend = 'local'`.
 - The upload router writes to Supabase Storage and `DELETE /files/{id}` removes the blob via the same adapter.
