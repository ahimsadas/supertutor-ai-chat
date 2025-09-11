# SuperTutor AI Chat

An AI RAG chatbot MVP using LangChain with Supabase pgvector, supporting multi-provider LLM switching, citations, and a React UI.

## Monorepo layout
- `backend/` — Python backend (to be implemented)
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
      and table_name in ('languages','curricula','files','chunks','threads','messages')
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
  - Provider API keys (OpenAI/Anthropic/Google/DeepSeek/xAI) are optional for now and will be used in later steps.
  - Supabase server-only variables `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are required only when you actually request a Supabase client in code.

