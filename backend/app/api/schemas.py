from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel


class ApiError(BaseModel):
    code: str
    message: str


class ApiSuccess(BaseModel):
    ok: bool = True
    data: Dict[str, Any] | None = None


class ApiFailure(BaseModel):
    ok: bool = False
    error: ApiError
