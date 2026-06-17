# Copyright (c) Microsoft. All rights reserved.

"""Historique des executions terminees (`src/tools/persistence.py`)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.api.dependencies import persistence_dependency
from src.tools.persistence import IncidentRecord, IncidentRecordSummary, PersistenceStore

router = APIRouter(prefix="/history", tags=["history"])


@router.get("")
async def list_history(
    limit: int = 20,
    store: PersistenceStore = Depends(persistence_dependency),
) -> list[IncidentRecordSummary]:
    return await store.list_records(limit=limit)


@router.get("/{run_id}")
async def get_history_record(
    run_id: str,
    store: PersistenceStore = Depends(persistence_dependency),
) -> IncidentRecord:
    record = await store.get_record(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return record
