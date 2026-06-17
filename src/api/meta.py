# Copyright (c) Microsoft. All rights reserved.

"""Parametres non sensibles exposes a l'UI (seuils, mode KB, mode modeles, scenarios)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.dependencies import settings_dependency
from src.config import Settings
from src.scenarios import DEFAULT_SCENARIO, SCENARIOS

router = APIRouter(tags=["meta"])


class MetaResponse(BaseModel):
    confidence_threshold: float
    max_reflection_loops: int
    kb_mode: str
    use_real_azure_openai: bool
    cosmos_enabled: bool


class ScenarioResponse(BaseModel):
    id: str
    label: str
    description: str


class ScenariosResponse(BaseModel):
    scenarios: list[ScenarioResponse]
    default: str


@router.get("/meta")
async def get_meta(settings: Settings = Depends(settings_dependency)) -> MetaResponse:
    return MetaResponse(
        confidence_threshold=settings.confidence_threshold,
        max_reflection_loops=settings.max_reflection_loops,
        kb_mode=settings.kb_mode,
        use_real_azure_openai=settings.use_real_azure_openai,
        cosmos_enabled=settings.cosmos_endpoint is not None,
    )


@router.get("/scenarios")
async def get_scenarios() -> ScenariosResponse:
    return ScenariosResponse(
        scenarios=[
            ScenarioResponse(id=s.id, label=s.label, description=s.description) for s in SCENARIOS.values()
        ],
        default=DEFAULT_SCENARIO,
    )
