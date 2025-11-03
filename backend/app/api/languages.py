from __future__ import annotations

from typing import List
from logging import getLogger

from fastapi import APIRouter
from pydantic import BaseModel

from app.languages.registry import get_enabled_languages_sorted


logger = getLogger("supertutor.languages")
router = APIRouter()


class LanguageOut(BaseModel):
    code: str
    name: str
    rtl: bool
    enabled: bool
    sort_order: int


class LanguagesResponse(BaseModel):
    languages: List[LanguageOut]


@router.get("/languages", response_model=LanguagesResponse)
def list_languages() -> LanguagesResponse:
    logger.debug("languages.list: registry")
    items = get_enabled_languages_sorted()
    return LanguagesResponse(languages=[LanguageOut(**i) for i in items])
