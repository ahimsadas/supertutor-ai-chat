from __future__ import annotations

from typing import List
from logging import getLogger

from fastapi import APIRouter
from pydantic import BaseModel

from app.providers.registry import list_providers, evaluate_provider_status


logger = getLogger("supertutor.providers")
router = APIRouter()


class ModelItem(BaseModel):
    id: str
    label: str


class ProviderItem(BaseModel):
    id: str
    name: str
    enabled: bool
    models: List[ModelItem]


class ProvidersResponse(BaseModel):
    providers: List[ProviderItem]


@router.get("/providers", response_model=ProvidersResponse)
def get_providers() -> ProvidersResponse:
    entries = list_providers()
    # Sort providers by display_name ASC; preserve models order
    entries = sorted(entries, key=lambda e: (e.get("display_name") or ""))

    providers_out: List[ProviderItem] = []
    for e in entries:
        enabled, reasons = evaluate_provider_status(e)
        if not enabled:
            # Concise debug line per disabled provider
            name = e.get("display_name") or e.get("id")
            reason_text = "; ".join(reasons) if reasons else "unknown"
            logger.debug(f"Provider disabled: {name} — {reason_text}")

        models_seq = e.get("models") or []
        model_items = [ModelItem(id=m, label=m) for m in models_seq]
        providers_out.append(
            ProviderItem(
                id=e.get("id"),
                name=e.get("display_name"),
                enabled=bool(enabled),
                models=model_items,
            )
        )

    return ProvidersResponse(providers=providers_out)
