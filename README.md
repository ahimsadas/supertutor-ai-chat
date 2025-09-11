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
