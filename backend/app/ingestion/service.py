from __future__ import annotations

from typing import BinaryIO, Dict, Optional
from logging import getLogger

from app.clients.supabase_client import get_supabase_client
from app.core.ingest_limits import ingest_cap_bytes


logger = getLogger("supertutor.ingestion")


class IngestionTooLargeError(Exception):
    """Raised when an input file exceeds the configured size cap."""


def _cap_bytes() -> int:
    # Backward compat wrapper; prefer ingest_cap_bytes()
    return ingest_cap_bytes()


def _enforce_size_cap(file_obj: BinaryIO, cap_bytes: int) -> int:
    """Stream from file_obj and enforce size cap; return measured size in bytes.

    Seeks to position 0 before and after. Raises IngestionTooLargeError if exceeded.
    """
    try:
        file_obj.seek(0)
    except Exception as e:
        logger.debug("ingest svc: seek(0) before read failed: %r", e)
        # If seek fails, we still attempt a read from current position
        pass

    total = 0
    chunk_size = 1024 * 1024
    while True:
        chunk = file_obj.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > cap_bytes:
            try:
                file_obj.seek(0)
            except Exception as e:
                logger.debug("ingest svc: seek(0) after overflow failed: %r", e)
            raise IngestionTooLargeError(f"size {total} exceeds cap {cap_bytes}")

    try:
        file_obj.seek(0)
    except Exception as e:
        logger.debug("ingest svc: seek(0) after read failed: %r", e)
    return total


def ingest_file(
    curriculum_id: str,
    file_obj: BinaryIO,
    filename: str,
    mime: str,
    sha256: str,
) -> Dict[str, object]:
    """Insert-or-dedupe file metadata and optionally enqueue processing.

    Returns:
        {"file_id": "<uuid>", "needs_processing": bool, "deduped": bool}
    """
    cap_bytes = ingest_cap_bytes()
    logger.info("ingest svc: fname=%s cap_bytes=%d", filename, cap_bytes)
    size = _enforce_size_cap(file_obj, cap_bytes)
    logger.info("ingest svc: fname=%s total_read=%d", filename, size)

    # Placeholder OCR decision: PDFs default to needs_ocr=False for now.
    needs_ocr = False
    if (mime or "").casefold() == "application/pdf":
        needs_ocr = False  # TODO(step 17): implement scanned-PDF detection

    client = get_supabase_client()

    # Idempotent insert-or-dedupe using UNIQUE(curriculum_id, sha256)
    # Strategy: SELECT first; if missing, INSERT; on duplicate, SELECT again.
    exists = (
        client
        .table("files")
        .select("id")
        .eq("curriculum_id", curriculum_id)
        .eq("sha256", sha256)
        .limit(1)
        .execute()
    )
    rows = exists.data or []
    if rows:
        file_id = rows[0].get("id")
        logger.debug(
            "ingest.service: deduped filename=%s sha256=%s... size=%s needs_ocr=%s",
            filename,
            (sha256 or "")[:12],
            size,
            needs_ocr,
        )
        # Optionally enqueue; if table does not exist, skip
        try:
            client.table("file_ingestion_jobs").insert({
                "file_id": file_id,
                "status": "pending",
            }).execute()
            job_enqueued = True
        except Exception:
            job_enqueued = False
            logger.debug("ingest.service: enqueue skipped (table not found)")
        return {"file_id": file_id, "needs_processing": True, "deduped": True, "job_enqueued": job_enqueued}

    # Not present: attempt insert
    try:
        ins = (
            client
            .table("files")
            .insert(
                {
                    "curriculum_id": curriculum_id,
                    "filename": filename,
                    "mime": mime,
                    "pages": None,
                    "sha256": sha256,
                }
            )
            .execute()
        )
        data = ins.data
        if isinstance(data, list) and data:
            row0 = data[0]
        elif isinstance(data, dict) and data:
            row0 = data
        else:
            # Fallback read-back for id
            sel2 = (
                client
                .table("files")
                .select("id")
                .eq("curriculum_id", curriculum_id)
                .eq("sha256", sha256)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            row0 = (sel2.data or [{}])[0]
        file_id = row0.get("id")
        logger.debug(
            "ingest.service: inserted filename=%s sha256=%s... size=%s needs_ocr=%s",
            filename,
            (sha256 or "")[:12],
            size,
            needs_ocr,
        )
        # Optionally enqueue
        try:
            client.table("file_ingestion_jobs").insert({
                "file_id": file_id,
                "status": "pending",
            }).execute()
            job_enqueued = True
        except Exception:
            job_enqueued = False
            logger.debug("ingest.service: enqueue skipped (table not found)")
        return {"file_id": file_id, "needs_processing": True, "deduped": False, "job_enqueued": job_enqueued}
    except Exception:
        # Possible race: duplicate key after concurrent insert
        sel = (
            client
            .table("files")
            .select("id")
            .eq("curriculum_id", curriculum_id)
            .eq("sha256", sha256)
            .limit(1)
            .execute()
        )
        rows2 = sel.data or []
        if not rows2:
            raise
        file_id = rows2[0].get("id")
        logger.debug(
            "ingest.service: deduped-after-conflict filename=%s sha256=%s... size=%s needs_ocr=%s",
            filename,
            (sha256 or "")[:12],
            size,
            needs_ocr,
        )
        try:
            client.table("file_ingestion_jobs").insert({
                "file_id": file_id,
                "status": "pending",
            }).execute()
            job_enqueued = True
        except Exception:
            job_enqueued = False
            logger.debug("ingest.service: enqueue skipped (table not found)")
        return {"file_id": file_id, "needs_processing": True, "deduped": True, "job_enqueued": job_enqueued}
