# Copyright (c) Microsoft. All rights reserved.

"""Parametres non sensibles exposes a l'UI (seuils, mode KB, mode modeles)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.dependencies import settings_dependency
from src.config import Settings

router = APIRouter(tags=["meta"])


class MetaResponse(BaseModel):
    confidence_threshold: float
    max_reflection_loops: int
    kb_mode: str
    use_real_azure_openai: bool
    cosmos_enabled: bool


@router.get("/meta")
async def get_meta(settings: Settings = Depends(settings_dependency)) -> MetaResponse:
    return MetaResponse(
        confidence_threshold=settings.confidence_threshold,
        max_reflection_loops=settings.max_reflection_loops,
        kb_mode=settings.kb_mode,
        use_real_azure_openai=settings.use_real_azure_openai,
        cosmos_enabled=settings.cosmos_endpoint is not None,
    )
