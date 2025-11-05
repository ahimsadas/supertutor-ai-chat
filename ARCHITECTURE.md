# Architecture Overview

This repository is a minimal monorepo scaffold. It will evolve as the design matures.

## Current Structure
- `backend/` — FastAPI backend with Supabase (pgvector), ingestion pipeline, and admin CLIs
- `frontend/` — placeholder for the React frontend application
- Root files:
  - `README.md` — project overview and setup
  - `ARCHITECTURE.md` — architecture and project tree (this document)
  - `postman_collection.json` — REST API collection for local testing
  - `.gitignore` — repository ignore rules

## Full Project Structure

```text
supertutor-ai-chat/
├── backend
│   ├── app
│   │   ├── api
│   │   │   ├── __init__.py
│   │   │   ├── errors.py
│   │   │   ├── languages.py
│   │   │   ├── providers.py
│   │   │   ├── responses.py
│   │   │   ├── schemas.py
│   │   │   ├── curricula.py
│   │   │   └── files.py
│   │   ├── cli
│   │   │   ├── __init__.py
│   │   │   ├── curricula.py
│   │   │   ├── files.py
│   │   │   ├── ingest.py
│   │   │   └── ingestion_jobs.py
│   │   ├── checkpointing
│   │   │   ├── __init__.py
│   │   │   └── postgres_checkpointer.py
│   │   ├── clients
│   │   │   ├── __init__.py
│   │   │   └── supabase_client.py
│   │   ├── core
│   │   │   ├── __init__.py
│   │   │   └── config.py
│   │   ├── ingestion
│   │   │   ├── __init__.py
│   │   │   ├── loader.py
│   │   │   ├── chunker.py
│   │   │   ├── embedder.py
│   │   │   ├── persist.py
│   │   │   ├── runner.py
│   │   │   └── service.py
│   │   ├── languages
│   │   │   ├── __init__.py
│   │   │   └── registry.py
│   │   ├── providers
│   │   │   ├── __init__.py
│   │   │   ├── provider_factory.py
│   │   │   └── registry.py
│   │   ├── storage
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── factory.py
│   │   │   └── supabase.py
│   │   ├── __init__.py
│   │   └── main.py
│   ├── sql
│   │   ├── 001_enable_pgvector.sql
│   │   ├── 002_schema_core.sql
│   │   ├── 003_index_hnsw.sql
│   │   ├── 004_rpc_match_documents.sql
│   │   ├── 005_files_chunks_constraints.sql
│   │   └── 006_files_storage_metadata.sql
│   ├── requirements.txt
│   ├── .env.example
│   └── .env
├── frontend
│   └── .gitkeep
├── .gitignore
├── ARCHITECTURE.md
├── README.md
└── postman_collection.json
```

- Excludes from tree for signal-to-noise: `.git`, `node_modules`, `.venv`, `venv`, `__pycache__`, `.mypy_cache`, `.pytest_cache`, `.idea`, `.vscode`, `dist`, `build`, `.DS_Store`.

## Configuration & Secrets

- `backend/.env.example` lists required variables for the backend.
- `backend/.env` is local-only and git-ignored; do not commit real values.
- The frontend will use public keys later via its own env file (separate from backend).

## Database migrations

- SQL migration stubs live under `backend/sql/`.
- For Supabase, execute these manually via Supabase Studio SQL Editor or `psql` against the project database.
- Vector indexes: HNSW indexes are added via `backend/sql/003_index_hnsw.sql` and can be tuned at query time using the `hnsw.ef_search` setting.
- RPCs: Application RPCs (e.g., `match_documents`) live under `backend/sql/` and are applied manually via Supabase Studio SQL Editor.

## Ingestion Job Runner

- Purpose: Scan recent files (or a specific file) and run the pipeline end-to-end: load (PDF/TXT) → chunk → embed → persist.
- Source documents are fetched from Supabase Storage via each file's `storage_key`; no local filesystem paths are used.
- Idempotency: if any rows already exist in `public.chunks` for a file, the runner skips re-inserting.
- The runner updates `files.pages` if the value is NULL (from loader page count).

CLI usage:

```bash
# From backend/
python -m app.cli.ingestion_jobs run --limit 5 --dry-run
python -m app.cli.ingestion_jobs run --file-id <uuid>
python -m app.cli.ingestion_jobs run --curriculum-id <uuid> --limit 20
```

## Chunking

- Per-page splitting using LangChain's `RecursiveCharacterTextSplitter` with overlap (`chunk_size`, `chunk_overlap`) and `add_start_index=True`.
- Fallback start index: if `start_index` metadata is missing, compute via substring search on the first 80, then 40 characters of the chunk; default to 0 if not found.
- Output chunk fields for the next step (embeddings): `{file_id, page, start_index, snippet}`.
- `snippet` is normalized to 350–500 characters when possible and derived from the page text around `start_index`.

## Embeddings & Persistence

- Embeddings model: OpenAI `text-embedding-3-small` (1536-d). Requires `OPENAI_API_KEY`.
- Batching: 64 snippets per request by default; preserves order.
- Inserts into `public.chunks` with fields `{file_id, page, start_index, snippet, embedding}` where `embedding` is `vector(1536)`.
- Logging includes a concise embedder summary per file and an overall runner summary with inserted counts.

## Storage layer

- A `StorageBackend` abstraction provides `put/get/delete/size` for binary objects.
- Single backend: Supabase Storage bucket `SUPABASE_FILES_BUCKET` (default `files`).
- Logical key convention: `files/{uuid}{ext}`. The upload router writes to Supabase; `DELETE /files/{id}` removes the blob.
 - Bucket resolution comes from settings (`SUPABASE_FILES_BUCKET`). On first use, the backend ensures the bucket exists. With a service role key, it will attempt to auto-create a private bucket if missing; otherwise it raises a clear error to create the bucket or set the env.

## Files storage metadata (DB)

- New columns on `public.files`:
  - `storage_key text` — logical key, by design `{uuid}{ext}`; adapters may apply prefixes/paths internally.
  - `size_bytes bigint` — object size in bytes.
  - `storage_backend text` — which backend wrote the object (historical; now `supabase`).
- Backfill for legacy rows initializes:
  - `storage_key = id::text || ext` where `ext` is derived from `mime`/`filename` (`.pdf`/`.txt` or empty).
  - `size_bytes = 0`.
  - `storage_backend = 'local'`.
- Constraint: `size_bytes` must be NULL or >= 0.
