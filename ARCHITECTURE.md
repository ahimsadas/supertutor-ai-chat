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

## Concise Project Structure

```text
supertutor-ai-chat/
├── backend
│   ├── app
│   │   ├── api/                 # REST endpoints: providers, languages, curricula, files
│   │   ├── cli/                 # Admin CLIs: curricula, files, ingest upload, ingestion_jobs
│   │   ├── core/                # Centralized settings loader (config.py)
│   │   ├── clients/             # External clients (supabase)
│   │   ├── ingestion/           # Loader, chunker, embedder, persist, runner, service
│   │   ├── languages/           # Language registry
│   │   ├── providers/           # Provider factory and registry
│   │   ├── storage/             # Storage backend abstraction (Supabase)
│   │   ├── checkpointing/       # LangGraph Postgres checkpointer
│   │   └── main.py              # FastAPI app wiring and debug endpoints
│   ├── sql/                     # SQL migrations and RPCs
│   ├── requirements.txt
│   ├── .env.example             # Documented env keys and defaults
│   └── .env                     # Local-only env (gitignored)
├── frontend/                    # Placeholder for React app
├── postman_collection.json      # Postman collection (uses {{baseUrl}})
└── README.md                    # Project overview and setup
```

### Key files

- `backend/app/core/config.py` — Settings object (pydantic-settings) auto-loads `backend/.env` for both server and CLIs; includes caps and embedding config.
- `backend/app/ingestion/runner.py` — Scans recent files, loads → chunks → embeds → persists. Enforces `FILES_INGEST_MAX_MB`.
- `backend/app/api/files.py` — `POST /files:ingest`, `GET /files`, `DELETE /files/{id}`; optional router preflight via `FILES_UPLOAD_MAX_MB`.
- `backend/app/ingestion/embedder.py` — Embedding client using `EMBEDDING_MODEL`, `EMBEDDING_BATCH_SIZE`, `EMBEDDING_DIM`.
- `backend/app/storage/supabase.py` — Supabase Storage adapter; bucket from `SUPABASE_FILES_BUCKET`.
