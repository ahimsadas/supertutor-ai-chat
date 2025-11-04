from __future__ import annotations

from typing import Any, Dict, List
from logging import getLogger

from langchain_text_splitters import RecursiveCharacterTextSplitter


logger = getLogger("supertutor.chunker")

# Defaults and bounds
DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 60
SNIPPET_MIN = 350
SNIPPET_MAX = 500


def _fallback_start_index(page_text: str, chunk_text: str) -> int:
    """Best-effort fallback when start_index metadata is missing.

    Tries to locate the chunk by searching the first 80 chars, then first 40 chars.
    Returns 0 if not found.
    """
    if not page_text or not chunk_text:
        return 0
    head80 = chunk_text[:80]
    idx = page_text.find(head80)
    if idx != -1:
        return max(0, idx)
    head40 = chunk_text[:40]
    idx2 = page_text.find(head40)
    if idx2 != -1:
        return max(0, idx2)
    return 0


def _normalize_snippet(page_text: str, start: int, chunk_text: str) -> str:
    """Return a 350–500 char snippet when possible.

    Rules:
    - If chunk is longer than SNIPPET_MAX → prefer chunk_text[:SNIPPET_MAX].rstrip(),
      but try page_text slice from `start` if available.
    - If chunk is shorter than SNIPPET_MIN → expand rightward from `start` on page_text,
      bounded by page length, up to SNIPPET_MAX.
    - Else → use the chunk text or matching page_text slice.
    Always return non-empty text.
    """
    # Guardrails
    if not page_text:
        return (chunk_text or "")[:SNIPPET_MAX].rstrip() or " "

    try:
        s = int(start)
    except Exception:
        s = 0
    s = max(0, min(s, max(0, len(page_text) - 1)))

    clen = len(chunk_text or "")

    # Case 1: chunk too long → prefer chunk slice, try page slice first when possible
    if clen > SNIPPET_MAX:
        if s < len(page_text):
            cand = page_text[s : min(len(page_text), s + SNIPPET_MAX)]
            if cand:
                return cand.rstrip()
        return (chunk_text or "")[:SNIPPET_MAX].rstrip()

    # Case 2: chunk too short → expand from start to at least SNIPPET_MIN
    if clen < SNIPPET_MIN:
        desired = max(SNIPPET_MIN, clen)
        e = min(len(page_text), s + min(desired, SNIPPET_MAX))
        snippet = page_text[s:e]
        if snippet:
            return snippet.rstrip()
        return (chunk_text or " ").rstrip()

    # Case 3: within bounds → try exact page slice length of chunk, else chunk
    if s < len(page_text):
        e = min(len(page_text), s + clen)
        cand = page_text[s:e]
        if cand:
            return cand.rstrip()
    return (chunk_text or " ").rstrip()


def chunk_pages(
    file_id: str,
    pages_struct: List[Dict[str, Any]],
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> List[Dict[str, Any]]:
    """Split each page into overlapping chunks and return chunk dicts.

    Each chunk dict has exactly: {"file_id","page","start_index","snippet"}.
    """
    chunks: List[Dict[str, Any]] = []
    pages_in = 0
    fallback_used = 0

    for idx, page in enumerate(pages_struct or []):
        try:
            page_no = int(page.get("page", idx + 1))  # type: ignore[arg-type]
        except Exception:
            page_no = idx + 1
        page_text = str(page.get("text", ""))
        if len(page_text.strip()) == 0:
            continue
        pages_in += 1

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            add_start_index=True,
        )
        docs = splitter.create_documents([page_text], metadatas=[{"page": page_no}])

        page_starts: List[int] = []
        page_chunk_count = 0
        for doc in docs:
            chunk_text = getattr(doc, "page_content", "") or ""
            if len(chunk_text.strip()) == 0:
                continue
            meta = getattr(doc, "metadata", {}) or {}
            start_meta = meta.get("start_index") if isinstance(meta, dict) else None
            if isinstance(start_meta, int):
                start = start_meta
            else:
                # Fallback path triggered
                fallback_used += 1
                start = _fallback_start_index(page_text, chunk_text)

            # Clamp start to valid range (page-relative, non-negative)
            try:
                start = int(start)
            except Exception:
                start = 0
            if start < 0:
                start = 0
            if start > len(page_text):
                start = max(0, len(page_text) - 1)

            snippet = _normalize_snippet(page_text, start, chunk_text)
            page_starts.append(int(start))

            chunks.append(
                {
                    "file_id": file_id,
                    "page": page_no,
                    "start_index": int(start),
                    "snippet": snippet,
                }
            )
            page_chunk_count += 1

        # Per-page debug: count and first few start indices
        logger.debug(
            "chunker.page file_id=%s page=%d chunks=%d starts_first=%s",
            file_id,
            page_no,
            page_chunk_count,
            page_starts[:5],
        )

    # File-level summary
    logger.info(
        "chunker.summary file_id=%s pages_in=%d chunks_out=%d",
        file_id,
        pages_in,
        len(chunks),
    )

    # Sample a few chunks for smoke-debugging
    for i, c in enumerate(chunks[:3]):
        logger.debug(
            "chunker.sample #%d file_id=%s page=%s start_index=%d snippet=%r",
            i + 1,
            file_id,
            c.get("page"),
            int(c.get("start_index", 0)),
            (c.get("snippet") or "")[:80],
        )

    if fallback_used:
        logger.debug("chunker.fallback_used file_id=%s count=%d", file_id, fallback_used)

    return chunks
