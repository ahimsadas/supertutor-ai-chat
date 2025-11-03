# Architecture Overview (Initial)

This repository is a minimal monorepo scaffold. It will evolve as the design matures.

## Current Structure
- `backend/` — placeholder for the Python backend service
- `frontend/` — placeholder for the React frontend application
- Root files:
  - `README.md` — project overview and layout
  - `ARCHITECTURE.md` — architecture outline (this document)
  - `.gitignore` — repository ignore rules

Note: This document will be updated as we implement components and refine the architecture.

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
│   │   │   └── curricula.py
│   │   ├── cli
│   │   │   ├── __init__.py
│   │   │   ├── curricula.py
│   │   │   ├── ingest.py
│   │   │   └── files.py
│   │   ├── checkpointing
│   │   │   ├── __init__.py
│   │   │   └── postgres_checkpointer.py
│   │   ├── clients
│   │   │   ├── __init__.py
│   │   │   └── supabase_client.py
│   │   ├── core
│   │   │   ├── __init__.py
│   │   │   └── config.py
│   │   ├── languages
│   │   │   ├── __init__.py
│   │   │   └── registry.py
│   │   ├── providers
│   │   │   ├── __init__.py
│   │   │   ├── provider_factory.py
│   │   │   └── registry.py
│   │   ├── __init__.py
│   │   └── main.py
│   ├── config
│   ├── routers
│   ├── services
│   ├── sql
│   │   ├── 001_enable_pgvector.sql
│   │   ├── 002_schema_core.sql
│   │   ├── 003_index_hnsw.sql
│   │   ├── 004_rpc_match_documents.sql
│   │   └── 005_files_chunks_constraints.sql
│   ├── tests
│   ├── .env
│   ├── .env.example
│   ├── .gitkeep
│   └── requirements.txt
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

