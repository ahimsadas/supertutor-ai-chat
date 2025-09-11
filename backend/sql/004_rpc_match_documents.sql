-- RPC: match_documents for LangChain SupabaseVectorStore
-- Prereqs: pgvector enabled (Step 3); HNSW index created (Step 5)
-- Called by LangChain with queryName = 'match_documents'.
-- JSONB filter uses @> containment, e.g. {"curriculum_id": "<uuid>"}.
-- Metadata is constructed inline from related tables (files, chunks).
-- Result limit: COALESCE(match_count, 10) with a hard cap of 200 via LEAST().

create or replace function public.match_documents(
  query_embedding vector(1536),
  match_count int default null,
  filter jsonb default '{}'::jsonb
)
returns table (
  id bigint,
  content text,
  metadata jsonb,
  embedding jsonb,
  similarity float
)
language plpgsql
as $$
begin
  return query
  select
    c.id,
    c.snippet as content,
    jsonb_build_object(
      'file_id', c.file_id,
      'page', c.page,
      'start_index', c.start_index,
      'curriculum_id', f.curriculum_id
    ) as metadata,
    (c.embedding::text)::jsonb as embedding,
    1 - (c.embedding <=> query_embedding) as similarity
  from public.chunks c
  join public.files f on f.id = c.file_id
  where (
    filter = '{}'::jsonb
    or jsonb_build_object(
         'file_id', c.file_id,
         'page', c.page,
         'start_index', c.start_index,
         'curriculum_id', f.curriculum_id
       ) @> filter
  )
  order by c.embedding <=> query_embedding
  limit least(coalesce(match_count, 10), 200);
end;
$$;
