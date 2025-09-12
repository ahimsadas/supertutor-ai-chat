from __future__ import annotations

from fastapi.responses import JSONResponse


def ok(data: dict, status: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status, content={"ok": True, "data": data})


def fail(code: str, message: str, status: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"ok": False, "error": {"code": code, "message": message}},
    )
