from __future__ import annotations

import time
from logging import getLogger
from typing import Any, Dict, List, Optional

from app.clients.supabase_client import get_supabase_client
from app.ingestion.loader import load_from_storage
from app.core.config import get_settings


logger = getLogger("supertutor.ingestion.runner")


def _infer_mime_from_ext(filename: str) -> str:
    from pathlib import Path
    suf = Path(filename or "").suffix.lower()
    if suf == ".pdf":
        return "application/pdf"
    if suf == ".txt":
        return "text/plain"
    return "application/octet-stream"


def _ensure_storage_key(row: Dict[str, Any]) -> Optional[str]:
    key = (row.get("storage_key") or "").strip()
    if key:
        # Normalize legacy keys that lack the 'files/' prefix
        if "/" not in key:
            return f"files/{key}"
        return key
    # Fallback: derive a likely key for Supabase bucket prefix
    fid = str(row.get("id") or "").strip()
    fname = str(row.get("filename") or "")
    ext = ""
    try:
        from pathlib import Path
        ext = Path(fname).suffix
    except Exception:
        ext = ""
    if not ext:
        m = str(row.get("mime") or "")
        if m == "application/pdf":
            ext = ".pdf"
        elif m == "text/plain":
            ext = ".txt"
    if not fid:
        return None
    return f"files/{fid}{ext}"


def _has_chunks(file_id: str) -> bool:
    client = get_supabase_client()
    r = (
        client
        .table("chunks")
        .select("id")
        .eq("file_id", file_id)
        .limit(1)
        .execute()
    )
    rows = r.data or []
    return bool(rows)


def run_pending_jobs(
    curriculum_id: Optional[str] = None,
    only_file_id: Optional[str] = None,
    limit: int = 10,
    dry_run: bool = False,
) -> Dict[str, Any]:
    client = get_supabase_client()

    scanned = 0
    processed = 0
    skipped = 0
    errors = 0
    details: List[Dict[str, Any]] = []

    candidates: List[Dict[str, Any]] = []

    if only_file_id:
        r = (
            client
            .table("files")
            .select("id,curriculum_id,filename,mime,storage_key,created_at")
            .eq("id", only_file_id)
            .limit(1)
            .execute()
        )
        rows = r.data or []
        if rows:
            candidates = [rows[0]]
        else:
            reason = "file-not-found"
            errors += 1
            details.append({"file_id": only_file_id, "status": "error", "reason": reason})
            return {
                "scanned": 0,
                "processed": 0,
                "skipped": 0,
                "errors": errors,
                "details": details,
            }
    else:
        q = client.table("files").select("id,curriculum_id,filename,mime,storage_key,created_at")
        if curriculum_id:
            q = q.eq("curriculum_id", curriculum_id)
        q = q.order("created_at", desc=True).limit(limit)
        r = q.execute()
        candidates = r.data or []

    logger.debug(
        "runner.selection: candidates=%d curriculum_id=%s only_file_id=%s limit=%d",
        len(candidates), curriculum_id, only_file_id, limit,
    )

    for row in candidates:
        file_id = str(row.get("id"))
        scanned += 1

        try:
            mime = row.get("mime") or _infer_mime_from_ext(str(row.get("filename") or ""))
            storage_key = _ensure_storage_key(row)
            logger.debug("runner.candidate file_id=%s key=%s mime=%s", file_id, storage_key, mime)

            if not storage_key:
                reason = "missing-storage-key"
                errors += 1
                details.append({"file_id": file_id, "status": "error", "reason": reason})
                continue

            already_chunked = _has_chunks(file_id)
            if only_file_id:
                if already_chunked:
                    reason = "chunks-exist"
                    skipped += 1
                    details.append({"file_id": file_id, "status": "skipped", "reason": reason})
                    continue
            else:
                if already_chunked:
                    reason = "already-chunked"
                    skipped += 1
                    details.append({"file_id": file_id, "status": "skipped", "reason": reason})
                    continue

            if dry_run:
                skipped += 1
                details.append({"file_id": file_id, "status": "skipped", "reason": "dry-run"})
                continue

            t0 = time.perf_counter()
            loaded: Optional[Dict[str, Any]] = None
            try:
                loaded = load_from_storage(file_id=file_id, storage_key=str(storage_key), mime=str(mime))
            except Exception as e:
                reason = (f"load-error: {e}")[:200]
                errors += 1
                details.append({"file_id": file_id, "status": "error", "reason": reason})
                continue
            finally:
                t1 = time.perf_counter()
                logger.debug(
                    "runner.load: file_id=%s secs=%.3f pages=%s needs_ocr=%s",
                    file_id,
                    (t1 - t0),
                    loaded.get("pages") if isinstance(loaded, dict) else None,
                    loaded.get("needs_ocr") if isinstance(loaded, dict) else None,
                )

            try:
                from app.ingestion.chunker import chunk_pages

                pages_struct = loaded.get("pages_struct") if isinstance(loaded, dict) else None
                if not isinstance(pages_struct, list):
                    raise RuntimeError("loaded.pages_struct missing or invalid")

                # Configurable chunk sizes via env (with sane defaults in chunker)
                s = get_settings()
                chunk_size = int(getattr(s, "CHUNK_SIZE_CHARS", 500) or 500)
                chunk_overlap = int(getattr(s, "CHUNK_OVERLAP_CHARS", 60) or 60)

                chunks = chunk_pages(
                    file_id=file_id,
                    pages_struct=pages_struct,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                )
                # TODO: step 16 - generate and persist embeddings for each chunk

                pages_count = int(loaded.get("pages") or len(pages_struct)) if isinstance(loaded, dict) else len(pages_struct)
                chunk_count = len(chunks)
                logger.debug(
                    "runner.chunker.done file_id=%s pages=%d chunks=%d", file_id, pages_count, chunk_count
                )
                processed += 1
                details.append({
                    "file_id": file_id,
                    "status": "processed",
                    "reason": "ok",
                    "pages": pages_count,
                    "chunks": chunk_count,
                })
            except Exception as e:
                reason = (f"chunker-error: {e}")[:200]
                errors += 1
                details.append({"file_id": file_id, "status": "error", "reason": reason})
        except Exception as e:
            reason = (f"internal-error: {e}")[:200]
            errors += 1
            details.append({"file_id": file_id, "status": "error", "reason": reason})

    logger.info(
        "runner.summary scanned=%d processed=%d skipped=%d errors=%d",
        scanned, processed, skipped, errors,
    )

    return {
        "scanned": scanned,
        "processed": processed,
        "skipped": skipped,
        "errors": errors,
        "details": details,
    }
