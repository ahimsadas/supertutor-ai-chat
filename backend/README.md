# Backend Configuration and Caps

Config is centralized in `app/core/config.py` using pydantic-settings, which auto-loads `backend/.env` for BOTH the FastAPI server and all CLI entrypoints.

Effective, non-secret settings are available via `settings_log_summary()` and logged at key boundaries:
- Files router (first call): `{FILES_UPLOAD_MAX_MB, SUPABASE_FILES_BUCKET}`
- CLI ingest upload (start): `{FILES_UPLOAD_MAX_MB, FILES_INGEST_MAX_MB}`
- Runner start: `{FILES_INGEST_MAX_MB}`

## Environment variables (backend/.env)
- BACKEND_BASE_URL (default http://localhost:8000)
- SUPABASE_URL (required when Supabase is used)
- SUPABASE_SERVICE_ROLE_KEY (required when Supabase is used)
- SUPABASE_DB_URL (optional; enables DB-optimized operations)
- SUPABASE_FILES_BUCKET (default files)
- FILES_UPLOAD_MAX_MB (float | empty) — optional router/HTTP preflight cap. Empty = no router cap.
- FILES_INGEST_MAX_MB (float, default 50) — runner/ingestion cap (marks files.ingestion_failed='size_cap').
- CHUNK_SIZE_CHARS (int, default 500)
- CHUNK_OVERLAP_CHARS (int, default 60)
- Provider keys (optional unless used): OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY, DEEPSEEK_API_KEY, XAI_API_KEY, OPENROUTER_API_KEY; and OpenRouter headers OPENROUTER_SITE_URL, OPENROUTER_APP_TITLE.

## Two caps, different semantics
- FILES_UPLOAD_MAX_MB (router preflight cap):
  - If set, the router will preflight stream and reject files over this cap before storage.
  - Behavior: response is HTTP 200 with the file listed in `rejected` and reason `too-large`.
  - If empty/omitted, the router has effectively no byte cap.
- FILES_INGEST_MAX_MB (runner cap):
  - Always enforced by the ingestion runner. If a file’s `size_bytes` exceeds this cap, the runner sets `files.ingestion_failed='size_cap'`, skips processing, and leaves chunks empty.

## Verification
- .env load: `GET /debug/env` returns `{ env_file, env_file_exists, openai_key_present }`.
- Router cap case: set `FILES_UPLOAD_MAX_MB=0.0001`, keep `FILES_INGEST_MAX_MB=50`. Upload any file via CLI → expect HTTP 200 JSON with the file in `rejected` and no DB `ingestion_failed` set.
- Runner cap case: set `FILES_UPLOAD_MAX_MB=` (empty) and `FILES_INGEST_MAX_MB=0.0001`. Upload succeeds; run `python -m app.cli.ingestion_jobs run --file-id <uuid>` → expect `files.ingestion_failed='size_cap'` and zero chunks.
