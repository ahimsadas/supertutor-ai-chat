from __future__ import annotations

from typing import List, Dict, Any
from logging import getLogger

logger = getLogger("supertutor.persist")


def persist_chunks(supabase, file_id: str, chunks: List[Dict[str, Any]], embeddings: List[List[float]]) -> int:
    if len(chunks) != len(embeddings):
        raise ValueError(f"persist_length_mismatch chunks={len(chunks)} embeddings={len(embeddings)}")

    if not chunks:
        return 0

    records: List[Dict[str, Any]] = []
    for c, emb in zip(chunks, embeddings):
        records.append(
            {
                "file_id": file_id,
                "page": int(c.get("page", 0) or 0),
                "start_index": int(c.get("start_index", 0) or 0),
                "snippet": str(c.get("snippet", "") or " "),
                "embedding": list(emb or []),
            }
        )

    resp = supabase.table("chunks").insert(records).execute()
    data = getattr(resp, "data", None)
    inserted = len(data or []) if isinstance(data, list) else len(records)

    logger.debug("persist.chunks inserted=%d file_id=%s", inserted, file_id)
    return inserted
