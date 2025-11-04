from __future__ import annotations

import hashlib
from typing import List, Optional, Tuple
from logging import getLogger
from pathlib import Path
import uuid

from fastapi import APIRouter, UploadFile, File, Form
from fastapi.responses import JSONResponse

from app.api.curricula import get_curriculum
from app.ingestion.service import ingest_file, IngestionTooLargeError
from app.core.ingest_limits import ingest_cap_bytes
from app.clients.supabase_client import get_supabase_client
from app.storage.factory import get_storage
from uuid import UUID


logger = getLogger("supertutor.files")
router = APIRouter()


ALLOWED_EXTS = {".pdf", ".txt"}


def _is_allowed_ext(filename: str) -> bool:
    return Path(filename or "").suffix.lower() in ALLOWED_EXTS


def _infer_mime_from_ext(filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext == ".pdf":
        return "application/pdf"
    if ext == ".txt":
        return "text/plain"
    return "application/octet-stream"


def _ext_for(filename: str, mime: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext in {".pdf", ".txt"}:
        return ext
    m = (mime or "").lower()
    if m == "application/pdf":
        return ".pdf"
    if m == "text/plain":
        return ".txt"
    return ext or ".bin"


async def _hash_upload_stream(upload: UploadFile, cap_bytes: int) -> Tuple[Optional[str], int, bool]:
    """Return (sha256_hex|None, size_bytes, too_large)."""
    hasher = hashlib.sha256()
    total = 0
    too_large = False
    try:
        # Ensure we start at the beginning for safety
        try:
            await upload.seek(0)
        except Exception as e:
            logger.debug("seek(0) failed: %r", e)
            try:
                upload.file.seek(0)  # type: ignore[attr-defined]
            except Exception as e2:
                logger.debug("file.seek(0) failed: %r", e2)
        chunk_size = 1024 * 1024
        while True:
            chunk = await upload.read(chunk_size)
            if not chunk:
                break
            total += len(chunk)
            if total > cap_bytes:
                too_large = True
                break
            hasher.update(chunk)
    finally:
        # Reset to beginning to avoid surprises for any later consumer
        try:
            await upload.seek(0)
        except Exception:
            try:
                upload.file.seek(0)  # type: ignore[attr-defined]
            except Exception:
                pass
    if too_large:
        return None, total, True
    return hasher.hexdigest(), total, False


@router.post("/files:ingest")
async def ingest_files(
    curriculum_id: str = Form(...),
    files: List[UploadFile] = File(...),
):
    # Validate curriculum
    row = get_curriculum(curriculum_id)
    if not row:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "NOT_FOUND", "message": "Curriculum not found"}},
        )

    if not files:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "MISSING_FILES", "message": "No files provided"}},
        )

    cap_bytes = ingest_cap_bytes()

    accepted: list[dict] = []
    rejected: list[dict] = []
    new_accepts = 0
    service_results: list[dict] = []

    for upload in files:
        name = upload.filename or "unnamed"
        if not _is_allowed_ext(name):
            rejected.append({"filename": name, "reason": "unsupported-extension"})
            try:
                await upload.close()
            except Exception:
                pass
            logger.debug("files.ingest: rejected ext name=%s", name)
            continue

        logger.info("ingest router: fname=%s cap_bytes=%d", name, cap_bytes)
        sha_hex, size, too_large = await _hash_upload_stream(upload, cap_bytes)
        logger.info("ingest router: fname=%s total_read=%d", name, size)

        if too_large:
            rejected.append({"filename": name, "reason": "too-large"})
            logger.debug(
                "files.ingest: rejected too-large name=%s size=%s cap=%s", name, size, cap_bytes
            )
            continue

        mime = upload.content_type or _infer_mime_from_ext(name)

        # Ensure pointer at start before passing to service
        try:
            await upload.seek(0)
        except Exception:
            try:
                upload.file.seek(0)  # type: ignore[attr-defined]
            except Exception:
                pass

        try:
            res = ingest_file(
                curriculum_id=curriculum_id,
                file_obj=upload.file,  # type: ignore[arg-type]
                filename=name,
                mime=mime,
                sha256=sha_hex or "",
            )

            file_id = res.get("file_id")
            deduped = bool(res.get("deduped"))
            if file_id and not deduped:
                try:
                    try:
                        await upload.seek(0)
                    except Exception:
                        try:
                            upload.file.seek(0)  # type: ignore[attr-defined]
                        except Exception:
                            pass
                    storage = get_storage()
                    ext = _ext_for(name, mime)
                    storage_key = storage.put(uuid.UUID(str(file_id)), upload.file, ext)
                    size_bytes = int(size)
                    storage_backend = "supabase"

                    client = get_supabase_client()
                    try:
                        (
                            client
                            .table("files")
                            .update({
                                "storage_key": storage_key,
                                "size_bytes": size_bytes,
                                "storage_backend": storage_backend,
                            })
                            .eq("id", str(file_id))
                            .execute()
                        )
                        logger.info(
                            "files.ingest: storage backend=%s file_id=%s key=%s size=%d",
                            storage_backend,
                            file_id,
                            storage_key,
                            size_bytes,
                        )
                    except Exception:
                        logger.exception("files.ingest: metadata update failed file_id=%s key=%s", file_id, storage_key)
                except Exception:
                    logger.exception("files.ingest: storage put failed file_id=%s", file_id)
        except IngestionTooLargeError:
            rejected.append({"filename": name, "reason": "too-large"})
            logger.debug(
                "files.ingest: service rejected too-large name=%s size=%s cap=%s", name, size, cap_bytes
            )
            try:
                await upload.close()
            except Exception:
                pass
            continue
        finally:
            # Close upload after service
            try:
                await upload.close()
            except Exception:
                pass

        service_results.append(res)
        file_id = res.get("file_id")
        deduped = bool(res.get("deduped"))
        accepted.append({"file_id": file_id, "filename": name, "deduped": deduped, "size": size})
        if not deduped:
            new_accepts += 1
        logger.debug(
            "files.ingest: %s name=%s size=%s sha256=%s...",
            "deduped" if deduped else "accepted",
            name,
            size,
            (sha_hex or "")[:12],
        )

    if new_accepts > 0:
        status = "accepted"
    else:
        # No new insertions (duplicates-only or everything rejected)
        status = "skipped"

    # REPORT: summarize cap and enqueue status (if any)
    enqueue_skipped = any(res.get("job_enqueued") is False for res in service_results)
    try:
        logger.info(
            "ingestion REPORT: cap_bytes=%s enqueue_skipped=%s example=%s",
            cap_bytes,
            enqueue_skipped,
            {
                "files": accepted[:1],
                "rejected": rejected[:1],
                "ingestion_status": status,
            },
        )
    except Exception:
        pass

    return JSONResponse(
        status_code=200,
        content={
            "files": accepted,
            "rejected": rejected,
            "ingestion_status": status,
        },
    )


@router.get("/files")
def list_files(curriculum_id: UUID):
    cid = str(curriculum_id)
    # Validate curriculum exists
    row = get_curriculum(cid)
    if not row:
        return JSONResponse(status_code=404, content={"detail": "Curriculum not found"})

    client = get_supabase_client()
    try:
        resp = (
            client
            .table("files")
            .select("id,curriculum_id,filename,mime,pages,sha256,created_at")
            .eq("curriculum_id", cid)
            .order("created_at", desc=True)
            .execute()
        )
        rows = resp.data or []
    except Exception:
        logger.exception("files.list: error listing files for curriculum_id=%s", cid)
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

    logger.debug("files.list: curriculum_id=%s count=%d", cid, len(rows))
    return JSONResponse(status_code=200, content={"files": rows})


@router.delete("/files/{file_id}")
def delete_file(file_id: UUID):
    fid = str(file_id)
    client = get_supabase_client()

    # Pre-delete chunk count
    try:
        cnt_resp = (
            client
            .table("chunks")
            .select("id")
            .eq("file_id", fid)
            .execute()
        )
        pre_count = len(cnt_resp.data or [])
    except Exception:
        logger.exception("files.delete: count chunks failed id=%s", fid)
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

    # Read storage metadata then attempt storage delete (idempotent)
    storage_key: Optional[str] = None
    try:
        meta_resp = (
            client
            .table("files")
            .select("storage_key,storage_backend")
            .eq("id", fid)
            .limit(1)
            .execute()
        )
        meta_rows = meta_resp.data or []
        if meta_rows:
            storage_key = meta_rows[0].get("storage_key")
    except Exception:
        logger.debug("files.delete: unable to read storage metadata id=%s", fid)

    if storage_key:
        try:
            storage = get_storage()
            storage.delete(storage_key)
            logger.info("files.delete: storage deleted key=%s", storage_key)
        except FileNotFoundError:
            logger.debug("files.delete: storage key missing key=%s", storage_key)
        except Exception:
            logger.exception("files.delete: storage delete failed key=%s", storage_key)

    # Delete file row (FK cascade removes chunks)
    try:
        del_resp = (
            client
            .table("files")
            .delete()
            .eq("id", fid)
            .execute()
        )
        deleted_rows = del_resp.data or []
        if not deleted_rows:
            return JSONResponse(status_code=404, content={"detail": "File not found"})
    except Exception:
        logger.exception("files.delete: delete failed id=%s", fid)
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

    logger.info("files.delete: file_id=%s chunks_pre=%d deleted=true", fid, pre_count)
    return JSONResponse(status_code=200, content={"deleted": {"file_id": fid, "chunks": pre_count}})
