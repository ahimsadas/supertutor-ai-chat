from __future__ import annotations

from typing import List, Optional
from logging import getLogger

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app.clients.supabase_client import get_supabase_client


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
def delete_curriculum_route(curriculum_id: str):
    row = get_curriculum(curriculum_id)
    if not row:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"code": "NOT_FOUND", "message": "Curriculum not found"}
            },
        )

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
    logger.debug("curricula.delete: deleted %s", curriculum_id)
    return Response(status_code=204)
