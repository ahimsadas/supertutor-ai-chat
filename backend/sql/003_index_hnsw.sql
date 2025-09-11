-- HNSW index for embeddings on public.chunks(embedding) using cosine distance.
-- Requires pgvector to be enabled first (see README Step 3).
-- Index type: HNSW (cosine), operator class: vector_cosine_ops.
-- Build-time params (defaults shown):
--   - m = 16 (controls graph connectivity)
--   - ef_construction = 64 (higher improves recall, increases build time/memory)
-- Query-time param:
--   - hnsw.ef_search (default 40; higher improves recall but slows queries)
-- Guidance: Create indexes AFTER initial data load for faster ingestion.
-- Production: Prefer CREATE INDEX CONCURRENTLY to avoid long table locks during build.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_chunks_embedding_hnsw_cosine
ON public.chunks
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
