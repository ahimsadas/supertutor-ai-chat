-- Core MVP schema for SuperTutor AI Chat.
-- Requires pgvector extension enabled first (see README Step 3).
-- Execute this script manually in Supabase Studio (SQL Editor) or via psql.
-- ANN indexes (HNSW/IVFFlat) for embeddings will be added later.

-- languages
create table if not exists public.languages (
  code text primary key,
  name text not null,
  rtl boolean not null default false,
  enabled boolean not null default true,
  sort_order int not null default 0,
  created_at timestamptz not null default now()
);

-- curricula
create table if not exists public.curricula (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  created_at timestamptz not null default now()
);

-- files
create table if not exists public.files (
  id uuid primary key default gen_random_uuid(),
  curriculum_id uuid not null references public.curricula(id) on delete cascade,
  filename text not null,
  mime text,
  pages int,
  sha256 text unique,
  created_at timestamptz not null default now()
);
create index if not exists idx_files_curriculum_id on public.files (curriculum_id);

-- chunks (requires vector(1536))
create table if not exists public.chunks (
  id bigserial primary key,
  file_id uuid not null references public.files(id) on delete cascade,
  page int not null,
  start_index int not null,
  snippet text not null,
  embedding vector(1536) not null,
  created_at timestamptz not null default now()
);
create index if not exists idx_chunks_file_id on public.chunks (file_id);
create index if not exists idx_chunks_file_page on public.chunks (file_id, page);

-- threads
create table if not exists public.threads (
  id uuid primary key default gen_random_uuid(),
  curriculum_id uuid not null references public.curricula(id) on delete cascade,
  provider text not null,
  model text not null,
  language_code text not null default 'auto' references public.languages(code) on update cascade on delete restrict,
  created_at timestamptz not null default now()
);
create index if not exists idx_threads_curriculum_id on public.threads (curriculum_id);

-- messages
create table if not exists public.messages (
  id bigserial primary key,
  thread_id uuid not null references public.threads(id) on delete cascade,
  role text not null,
  content text not null,
  citations jsonb,
  created_at timestamptz not null default now()
);
create index if not exists idx_messages_thread_id on public.messages (thread_id);
