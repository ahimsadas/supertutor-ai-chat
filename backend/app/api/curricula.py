from __future__ import annotations

from typing import List, Optional
from logging import getLogger

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app.clients.supabase_client import get_supabase_client
from app.core.config import get_settings
import psycopg  # type: ignore
from psycopg.rows import dict_row  # type: ignore


logger = getLogger("supertutor.curricula")
router = APIRouter()


class CurriculumOut(BaseModel):
    id: str
    name: str
    created_at: str


class CurriculaResponse(BaseModel):
    curricula: List[CurriculumOut]


class CreateCurriculumBody(BaseModel):
    name: str


def _normalize_name(name: str) -> str:
    return (name or "").strip()


def _escape_like_pattern(s: str) -> str:
    s = s.replace("\\", "\\\\")
    s = s.replace("%", "\\%")
    s = s.replace("_", "\\_")
    return s


_FK_CASCADE_CHUNKS_FILES: Optional[bool] = None


def _get_db_uri() -> Optional[str]:
    try:
        settings = get_settings()
        return settings.SUPABASE_DB_URL
    except Exception:
        return None


def _curriculum_exists(curriculum_id: str) -> bool:
    return bool(get_curriculum(curriculum_id))


def _counts_for_curriculum_tx(cur, curriculum_id: str) -> dict:
    cur.execute(
        "SELECT count(*) AS c FROM public.files WHERE curriculum_id = %s",
        (curriculum_id,),
    )
    files_count = int(cur.fetchone()["c"])
    cur.execute(
        """
        SELECT count(*) AS c
        FROM public.chunks ch
        JOIN public.files f ON f.id = ch.file_id
        WHERE f.curriculum_id = %s
        """,
        (curriculum_id,),
    )
    chunks_count = int(cur.fetchone()["c"])
    cur.execute(
        "SELECT count(*) AS c FROM public.threads WHERE curriculum_id = %s",
        (curriculum_id,),
    )
    threads_count = int(cur.fetchone()["c"])
    return {"files": files_count, "chunks": chunks_count, "threads": threads_count}


def _counts_for_curriculum(curriculum_id: str) -> dict:
    db_uri = _get_db_uri()
    if db_uri:
        with psycopg.connect(db_uri, autocommit=True, row_factory=dict_row) as conn:  # type: ignore
            with conn.cursor() as cur:  # type: ignore
                return _counts_for_curriculum_tx(cur, curriculum_id)
    client = get_supabase_client()
    files_count = count_files_for_curriculum(curriculum_id)
    threads_count = count_threads_for_curriculum(curriculum_id)
    files_res = (
        client.table("files").select("id").eq("curriculum_id", curriculum_id).execute()
    )
    file_ids = [r["id"] for r in (files_res.data or [])]
    chunks_count = 0
    if file_ids:
        chunks_res = (
            client.table("chunks")
            .select("id", count="exact")
            .in_("file_id", file_ids)
            .execute()
        )
        cnt = getattr(chunks_res, "count", None)
        chunks_count = int(cnt) if cnt is not None else len(chunks_res.data or [])
    return {"files": files_count, "chunks": chunks_count, "threads": threads_count}


def _has_fk_cascade_chunks_to_files() -> bool:
    global _FK_CASCADE_CHUNKS_FILES
    if _FK_CASCADE_CHUNKS_FILES is not None:
        return _FK_CASCADE_CHUNKS_FILES
    db_uri = _get_db_uri()
    if not db_uri:
        _FK_CASCADE_CHUNKS_FILES = False
        return False
    try:
        with psycopg.connect(db_uri, autocommit=True, row_factory=dict_row) as conn:  # type: ignore
            with conn.cursor() as cur:  # type: ignore
                cur.execute(
                    """
                    SELECT c.confdeltype
                    FROM pg_constraint c
                    JOIN pg_class t ON t.oid = c.conrelid
                    JOIN pg_namespace tn ON tn.oid = t.relnamespace
                    JOIN pg_class r ON r.oid = c.confrelid
                    JOIN pg_namespace rn ON rn.oid = r.relnamespace
                    WHERE c.contype='f'
                      AND tn.nspname='public' AND t.relname='chunks'
                      AND rn.nspname='public' AND r.relname='files'
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
                _FK_CASCADE_CHUNKS_FILES = bool(row and row.get("confdeltype") == "c")
                return bool(_FK_CASCADE_CHUNKS_FILES)
    except Exception:
        _FK_CASCADE_CHUNKS_FILES = False
        return False


def _delete_files_and_chunks_for_curriculum(curriculum_id: str, has_fk_cascade: bool, cur=None) -> None:
    if cur is not None:
        if not has_fk_cascade:
            cur.execute(
                "DELETE FROM public.chunks WHERE file_id IN (SELECT id FROM public.files WHERE curriculum_id = %s)",
                (curriculum_id,),
            )
        cur.execute(
            "DELETE FROM public.files WHERE curriculum_id = %s",
            (curriculum_id,),
        )
        return
    db_uri = _get_db_uri()
    if not db_uri:
        return
    with psycopg.connect(db_uri, autocommit=False, row_factory=dict_row) as conn:  # type: ignore
        with conn.cursor() as _cur:  # type: ignore
            if not has_fk_cascade:
                _cur.execute(
                    "DELETE FROM public.chunks WHERE file_id IN (SELECT id FROM public.files WHERE curriculum_id = %s)",
                    (curriculum_id,),
                )
            _cur.execute(
                "DELETE FROM public.files WHERE curriculum_id = %s",
                (curriculum_id,),
            )
            conn.commit()


def list_curricula() -> List[dict]:
    client = get_supabase_client()
    res = (
        client.table("curricula")
        .select("id,name,created_at")
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


def find_curriculum_by_name_casefold(name: str) -> Optional[dict]:
    n = _normalize_name(name)
    if not n:
        return None
    client = get_supabase_client()
    pattern = _escape_like_pattern(n)
    res = (
        client.table("curricula")
        .select("id,name,created_at")
        .ilike("name", pattern)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def insert_curriculum(name: str) -> dict:
    n = _normalize_name(name)
    client = get_supabase_client()
    res = client.table("curricula").insert({"name": n}).execute()
    data = res.data
    if isinstance(data, list) and data:
        return data[0]
    if isinstance(data, dict) and data:
        return data
    res2 = (
        client.table("curricula")
        .select("id,name,created_at")
        .eq("name", n)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = res2.data or []
    return rows[0] if rows else {}


def get_curriculum(curriculum_id: str) -> Optional[dict]:
    client = get_supabase_client()
    res = (
        client.table("curricula")
        .select("id,name,created_at")
        .eq("id", curriculum_id)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def count_files_for_curriculum(curriculum_id: str) -> int:
    client = get_supabase_client()
    res = (
        client.table("files")
        .select("id", count="exact")
        .eq("curriculum_id", curriculum_id)
        .execute()
    )
    cnt = getattr(res, "count", None)
    if cnt is None:
        cnt = len(res.data or [])
    return int(cnt)


def count_threads_for_curriculum(curriculum_id: str) -> int:
    client = get_supabase_client()
    res = (
        client.table("threads")
        .select("id", count="exact")
        .eq("curriculum_id", curriculum_id)
        .execute()
    )
    cnt = getattr(res, "count", None)
    if cnt is None:
        cnt = len(res.data or [])
    return int(cnt)


def delete_curriculum(curriculum_id: str) -> None:
    client = get_supabase_client()
    _ = client.table("curricula").delete().eq("id", curriculum_id).execute()


@router.get("/curricula", response_model=CurriculaResponse)
def list_curricula_route() -> CurriculaResponse:
    logger.debug("curricula.list: querying")
    rows = list_curricula()
    return CurriculaResponse(curricula=[CurriculumOut(**r) for r in rows])


@router.post("/curricula", response_model=CurriculumOut)
def create_curriculum_route(body: CreateCurriculumBody) -> CurriculumOut:
    name = _normalize_name(body.name)
    if not name:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "INVALID_NAME", "message": "Name must be non-empty"}},
        )
    if len(name) > 200:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "INVALID_NAME",
                    "message": "Name must be at most 200 characters",
                }
            },
        )

    existing = find_curriculum_by_name_casefold(name)
    if existing:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "DUPLICATE",
                    "message": "Curriculum with this name exists",
                }
            },
        )

    row = insert_curriculum(name)
    logger.debug("curricula.create: inserted %s", row.get("id"))
    return CurriculumOut(**row)


@router.delete("/curricula/{curriculum_id}")
def delete_curriculum_route(curriculum_id: str, force: bool = False):
    row = get_curriculum(curriculum_id)
    if not row:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"code": "NOT_FOUND", "message": "Curriculum not found"}
            },
        )

    if not force:
        files_count = count_files_for_curriculum(curriculum_id)
        threads_count = count_threads_for_curriculum(curriculum_id)
        if files_count > 0 or threads_count > 0:
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "code": "FORBIDDEN_DELETE",
                        "message": "Curriculum has related data",
                        "counts": {"files": files_count, "threads": threads_count},
                    }
                },
            )
        delete_curriculum(curriculum_id)
        logger.debug("curricula.delete: id=%s force=false files=%d chunks=%d threads=%d", curriculum_id, 0, 0, 0)
        return Response(status_code=204)

    db_uri = _get_db_uri()
    has_fk = _has_fk_cascade_chunks_to_files()
    if db_uri:
        with psycopg.connect(db_uri, autocommit=False, row_factory=dict_row) as conn:  # type: ignore
            with conn.cursor() as cur:  # type: ignore
                counts = _counts_for_curriculum_tx(cur, curriculum_id)
                if counts.get("threads", 0) > 0:
                    conn.rollback()
                    return JSONResponse(
                        status_code=409,
                        content={
                            "error": {
                                "code": "FORBIDDEN_DELETE_THREADS",
                                "message": "Curriculum has active threads",
                                "counts": counts,
                            }
                        },
                    )
                if counts.get("files", 0) > 0:
                    _delete_files_and_chunks_for_curriculum(curriculum_id, has_fk, cur=cur)
                cur.execute("DELETE FROM public.curricula WHERE id = %s", (curriculum_id,))
                conn.commit()
                logger.debug(
                    "curricula.delete: id=%s force=true files=%d chunks=%d threads=%d",
                    curriculum_id,
                    counts.get("files", 0),
                    counts.get("chunks", 0),
                    counts.get("threads", 0),
                )
                return JSONResponse(
                    status_code=200,
                    content={
                        "deleted": {
                            "curriculum_id": curriculum_id,
                            "files": counts.get("files", 0),
                            "chunks": counts.get("chunks", 0),
                            "threads": 0,
                        }
                    },
                )

    client = get_supabase_client()
    counts = _counts_for_curriculum(curriculum_id)
    if counts.get("threads", 0) > 0:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "FORBIDDEN_DELETE_THREADS",
                    "message": "Curriculum has active threads",
                    "counts": counts,
                }
            },
        )
    if counts.get("files", 0) > 0:
        files_res = client.table("files").select("id").eq("curriculum_id", curriculum_id).execute()
        file_ids = [r["id"] for r in (files_res.data or [])]
        if file_ids and not has_fk:
            client.table("chunks").delete().in_("file_id", file_ids).execute()
        client.table("files").delete().eq("curriculum_id", curriculum_id).execute()
    client.table("curricula").delete().eq("id", curriculum_id).execute()
    logger.debug(
        "curricula.delete: id=%s force=true files=%d chunks=%d threads=%d",
        curriculum_id,
        counts.get("files", 0),
        counts.get("chunks", 0),
        counts.get("threads", 0),
    )
    return JSONResponse(
        status_code=200,
        content={
            "deleted": {
                "curriculum_id": curriculum_id,
                "files": counts.get("files", 0),
                "chunks": counts.get("chunks", 0),
                "threads": 0,
            }
        },
    )
