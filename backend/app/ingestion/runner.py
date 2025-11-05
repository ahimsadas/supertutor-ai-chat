from __future__ import annotations

import time
from logging import getLogger
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from app.clients.supabase_client import get_supabase_client
from app.ingestion.loader import load_from_storage
from app.core.config import get_settings, settings_log_summary
from app.core.ingest_limits import ingest_cap_bytes


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


def _get_db_uri() -> Optional[str]:
    try:
        s = get_settings()
        return s.SUPABASE_DB_URL
    except Exception:
        return None


def _clone_chunks_via_db(target_file_id: str, source_file_id: str) -> int:
    db_uri = _get_db_uri()
    if not db_uri:
        return 0
    try:
        import psycopg  # type: ignore
        from psycopg.rows import dict_row  # type: ignore
    except Exception:
        return 0
    inserted = 0
    try:
        with psycopg.connect(db_uri, autocommit=True, row_factory=dict_row) as conn:  # type: ignore
            with conn.cursor() as cur:  # type: ignore
                cur.execute(
                    """
                    INSERT INTO public.chunks(file_id, page, start_index, snippet, embedding)
                    SELECT %s, page, start_index, snippet, embedding
                    FROM public.chunks WHERE file_id = %s
                    """,
                    (target_file_id, source_file_id),
                )
                inserted = int(cur.rowcount or 0)
    except Exception:
        logger.debug("runner.clone.db.failed target=%s source=%s", target_file_id, source_file_id)
        return 0
    return inserted


def _clone_chunks_via_client(client, target_file_id: str, source_file_id: str) -> int:
    page_size = 1000
    offset = 0
    total_inserted = 0
    while True:
        res = (
            client.table("chunks")
            .select("page,start_index,snippet,embedding")
            .eq("file_id", source_file_id)
            .order("id")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            break
        records: List[Dict[str, Any]] = []
        for ch in rows:
            records.append(
                {
                    "file_id": target_file_id,
                    "page": int(ch.get("page", 0) or 0),
                    "start_index": int(ch.get("start_index", 0) or 0),
                    "snippet": str(ch.get("snippet", "") or " "),
                    "embedding": list(ch.get("embedding") or []),
                }
            )
        if records:
            ins = client.table("chunks").insert(records).execute()
            data = getattr(ins, "data", None)
            total_inserted += len(data or records)
        if len(rows) < page_size:
            break
        offset += page_size
    return total_inserted


def run_pending_jobs(
    curriculum_id: Optional[str] = None,
    only_file_id: Optional[str] = None,
    limit: int = 10,
    dry_run: bool = False,
) -> Dict[str, Any]:
    client = get_supabase_client()
    # Log effective ingestion cap per invocation
    try:
        logger.info("runner.settings %s", settings_log_summary(["FILES_INGEST_MAX_MB"]))
    except Exception:
        pass

    scanned = 0
    processed = 0
    skipped = 0
    errors = 0
    inserted_total = 0
    details: List[Dict[str, Any]] = []

    candidates: List[Dict[str, Any]] = []

    if only_file_id:
        r = (
            client
            .table("files")
            .select("id,curriculum_id,filename,mime,storage_key,size_bytes,sha256,created_at")
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
        q = client.table("files").select("id,curriculum_id,filename,mime,storage_key,size_bytes,sha256,created_at")
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

            # (a) Defensive size cap re-check based on DB metadata
            try:
                max_bytes = ingest_cap_bytes()
            except Exception:
                max_bytes = 50 * 1024 * 1024
            size_bytes = row.get("size_bytes")
            try:
                size_val = int(size_bytes) if size_bytes is not None else None
            except Exception:
                size_val = None
            if size_val is not None and size_val > max_bytes:
                # Update files: mark failure and processed_at
                ts = datetime.now(timezone.utc).isoformat()
                db_uri = _get_db_uri()
                updated = False
                if db_uri:
                    try:
                        import psycopg  # type: ignore
                        with psycopg.connect(db_uri, autocommit=True) as conn:  # type: ignore
                            with conn.cursor() as cur:  # type: ignore
                                cur.execute(
                                    "UPDATE public.files SET ingestion_failed='size_cap', processed_at=now() WHERE id=%s",
                                    (file_id,),
                                )
                                updated = True
                    except Exception:
                        updated = False
                if not updated:
                    try:
                        client.table("files").update({
                            "ingestion_failed": "size_cap",
                            "processed_at": ts,
                        }).eq("id", file_id).execute()
                    except Exception:
                        logger.debug("runner.size_cap.update.failed file_id=%s", file_id)
                skipped += 1
                details.append({
                    "file_id": file_id,
                    "status": "failed",
                    "reason": "size_cap",
                    "pages": 0,
                    "chunks": 0,
                    "inserted": 0,
                })
                continue

            # (b) Cross-file dedupe by sha256 (clone chunks)
            sha256 = (row.get("sha256") or "").strip()
            if sha256:
                # Find another file with same sha256 that already has chunks
                try:
                    others = (
                        client.table("files")
                        .select("id")
                        .eq("sha256", sha256)
                        .neq("id", file_id)
                        .order("created_at", desc=True)
                        .limit(10)
                        .execute()
                    )
                    other_rows = others.data or []
                except Exception:
                    other_rows = []
                source_id: Optional[str] = None
                source_chunks_count = 0
                for o in other_rows:
                    sid = o.get("id")
                    if not sid:
                        continue
                    try:
                        chres = (
                            client.table("chunks")
                            .select("id", count="exact")
                            .eq("file_id", sid)
                            .execute()
                        )
                        cnt = getattr(chres, "count", None)
                        source_chunks_count = int(cnt) if cnt is not None else len(chres.data or [])
                        if source_chunks_count > 0:
                            source_id = sid
                            break
                    except Exception:
                        continue
                if source_id and source_chunks_count > 0:
                    inserted_clone = 0
                    # Prefer DB-side clone when direct DB URL is available
                    inserted_clone = _clone_chunks_via_db(file_id, source_id) or 0
                    if inserted_clone == 0:
                        inserted_clone = _clone_chunks_via_client(client, file_id, source_id)
                    # Mark processed_at
                    ts = datetime.now(timezone.utc).isoformat()
                    db_uri = _get_db_uri()
                    updated = False
                    if db_uri:
                        try:
                            import psycopg  # type: ignore
                            with psycopg.connect(db_uri, autocommit=True) as conn:  # type: ignore
                                with conn.cursor() as cur:  # type: ignore
                                    cur.execute(
                                        "UPDATE public.files SET processed_at=now() WHERE id=%s",
                                        (file_id,),
                                    )
                                    updated = True
                        except Exception:
                            updated = False
                    if not updated:
                        try:
                            client.table("files").update({"processed_at": ts}).eq("id", file_id).execute()
                        except Exception:
                            logger.debug("runner.clone.processed_at.update.failed file_id=%s", file_id)

                    # Update global inserted_total
                    try:
                        inserted_total += int(inserted_clone or 0)
                    except Exception:
                        pass

                    # Derive pages count for reporting and optional backfill
                    pages_count_clone = 0
                    try:
                        src_pg = (
                            client.table("files")
                            .select("pages")
                            .eq("id", source_id)
                            .limit(1)
                            .execute()
                        )
                        src_rows = src_pg.data or []
                        v = src_rows[0].get("pages") if src_rows else None
                        if v is not None:
                            pages_count_clone = int(v)
                        if pages_count_clone <= 0:
                            # Fallback: infer from max(page) in chunks
                            pg_res = (
                                client.table("chunks")
                                .select("page")
                                .eq("file_id", source_id)
                                .order("page", desc=True)
                                .limit(1)
                                .execute()
                            )
                            pgr = pg_res.data or []
                            if pgr:
                                pages_count_clone = int(pgr[0].get("page") or 0)
                    except Exception:
                        pages_count_clone = pages_count_clone or 0

                    # Backfill target files.pages if NULL only
                    try:
                        r_curr = (
                            client
                            .table("files")
                            .select("pages")
                            .eq("id", file_id)
                            .limit(1)
                            .execute()
                        )
                        rows_curr = r_curr.data or []
                        if rows_curr and rows_curr[0].get("pages") is None and pages_count_clone > 0:
                            client.table("files").update({"pages": pages_count_clone}).eq("id", file_id).execute()
                    except Exception:
                        logger.debug("runner.clone.pages.update.skip file_id=%s", file_id)

                    processed += 1
                    details.append({
                        "file_id": file_id,
                        "status": "processed",
                        "reason": "clone_from",
                        "pages": pages_count_clone,
                        "chunks": inserted_clone,
                        "inserted": inserted_clone,
                        "source_id": source_id,
                    })
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

            # (c) OCR triage: if suspected scanned PDF, mark and skip
            try:
                if isinstance(loaded, dict) and bool(loaded.get("ocr_suspected")):
                    ts = datetime.now(timezone.utc).isoformat()
                    db_uri = _get_db_uri()
                    updated = False
                    if db_uri:
                        try:
                            import psycopg  # type: ignore
                            with psycopg.connect(db_uri, autocommit=True) as conn:  # type: ignore
                                with conn.cursor() as cur:  # type: ignore
                                    cur.execute(
                                        "UPDATE public.files SET needs_ocr=true, processed_at=now() WHERE id=%s",
                                        (file_id,),
                                    )
                                    updated = True
                        except Exception:
                            updated = False
                    if not updated:
                        try:
                            client.table("files").update({
                                "needs_ocr": True,
                                "processed_at": ts,
                            }).eq("id", file_id).execute()
                        except Exception:
                            logger.debug("runner.ocr.update.failed file_id=%s", file_id)
                    skipped += 1
                    details.append({
                        "file_id": file_id,
                        "status": "skipped",
                        "reason": "ocr_required",
                        "pages": int(loaded.get("pages", 0)),
                        "chunks": 0,
                        "inserted": 0,
                    })
                    continue
            except Exception:
                logger.debug("runner.ocr.triage.unexpected file_id=%s", file_id)

            try:
                from app.ingestion.chunker import chunk_pages
                from app.ingestion.embedder import embed_snippets
                from app.ingestion.persist import persist_chunks
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

                # Determine page and chunk counts
                pages_count = int(loaded.get("pages") or len(pages_struct)) if isinstance(loaded, dict) else len(pages_struct)
                chunk_count = len(chunks)

                # Short-circuit when no chunks were produced
                if chunk_count == 0:
                    # Update files.pages if null only
                    try:
                        r_curr = (
                            client
                            .table("files")
                            .select("pages")
                            .eq("id", file_id)
                            .limit(1)
                            .execute()
                        )
                        rows_curr = r_curr.data or []
                        if rows_curr and rows_curr[0].get("pages") is None:
                            client.table("files").update({"pages": pages_count}).eq("id", file_id).execute()
                    except Exception:
                        logger.debug("runner.pages.update.skip file_id=%s", file_id)

                    processed += 1
                    details.append({
                        "file_id": file_id,
                        "status": "processed",
                        "reason": "ok",
                        "pages": pages_count,
                        "chunks": chunk_count,
                        "inserted": 0,
                    })
                    continue

                # Generate embeddings and persist
                snippets = [str(c.get("snippet", "") or " ") for c in chunks]
                t_emb0 = time.perf_counter()
                # Use embedding batch size from settings (fallback 64 inside embedder)
                s = get_settings()
                bs = int(getattr(s, "EMBEDDING_BATCH_SIZE", 64) or 64)
                embeddings = embed_snippets(snippets, batch_size=bs)
                t_emb1 = time.perf_counter()
                inserted = persist_chunks(client, file_id, chunks, embeddings)
                inserted_total += int(inserted or 0)

                # Update files.pages if null only
                try:
                    r_curr = (
                        client
                        .table("files")
                        .select("pages")
                        .eq("id", file_id)
                        .limit(1)
                        .execute()
                    )
                    rows_curr = r_curr.data or []
                    if rows_curr and rows_curr[0].get("pages") is None:
                        client.table("files").update({"pages": pages_count}).eq("id", file_id).execute()
                except Exception:
                    logger.debug("runner.pages.update.skip file_id=%s", file_id)

                try:
                    model = getattr(s, "EMBEDDING_MODEL", "text-embedding-3-small") or "text-embedding-3-small"
                    dim = int(getattr(s, "EMBEDDING_DIM", 1536) or 1536)
                except Exception:
                    model, dim = "text-embedding-3-small", 1536
                logger.info(
                    "embedder.summary file_id=%s model=%s snippets=%d inserted=%d dim=%d secs=%.3f",
                    file_id,
                    model,
                    len(snippets),
                    inserted,
                    dim,
                    (t_emb1 - t_emb0),
                )

                # Mark processed_at and clear failure flags, needs_ocr
                ts = datetime.now(timezone.utc).isoformat()
                db_uri = _get_db_uri()
                updated = False
                if db_uri:
                    try:
                        import psycopg  # type: ignore
                        with psycopg.connect(db_uri, autocommit=True) as conn:  # type: ignore
                            with conn.cursor() as cur:  # type: ignore
                                cur.execute(
                                    "UPDATE public.files SET processed_at=now(), needs_ocr=false, ingestion_failed=NULL WHERE id=%s",
                                    (file_id,),
                                )
                                updated = True
                    except Exception:
                        updated = False
                if not updated:
                    try:
                        client.table("files").update({
                            "processed_at": ts,
                            "needs_ocr": False,
                            "ingestion_failed": None,
                        }).eq("id", file_id).execute()
                    except Exception:
                        logger.debug("runner.processed_at.update.failed file_id=%s", file_id)

                processed += 1
                details.append({
                    "file_id": file_id,
                    "status": "processed",
                    "reason": "ok",
                    "pages": pages_count,
                    "chunks": chunk_count,
                    "inserted": inserted,
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
        "runner.summary scanned=%d processed=%d skipped=%d errors=%d inserted=%d",
        scanned, processed, skipped, errors, inserted_total,
    )

    return {
        "scanned": scanned,
        "processed": processed,
        "skipped": skipped,
        "errors": errors,
        "inserted": inserted_total,
        "details": details,
    }
