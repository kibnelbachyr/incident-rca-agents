# Copyright (c) Microsoft. All rights reserved.

"""Endpoints d'execution du workflow (SSE) - coeur de l'API.

Le diagnostic se deroule en deux phases HTTP, chacune un flux SSE
(`text/event-stream`) :

1. `POST /api/runs` : cree une nouvelle execution (un `Workflow` via
   `build_workflow`, DECISIONS.md #16) et streame `step` (sortie de chaque
   agent, y compris la boucle `RootCause <-> GatherEvidence`) jusqu'a la
   porte humaine (`approval_required`) ou la fin (`done`).
2. `POST /api/runs/{run_id}/approval` : reprend le MEME `Workflow` (`responses=
   {request_id: bool}`, DECISIONS.md #14) et streame le reste (refus =
   `human_approval` seul ; approbation = `remediation` + `summary`), puis
   persiste le `SharedContext` final (`src/tools/persistence.py`) et emet
   `done`.

Le `Workflow` de la phase 1 doit rester en memoire jusqu'a l'appel de
l'approbation (ses executeurs, notamment `HumanApprovalExecutor`, portent de
l'etat - DECISIONS.md #14) : il est garde dans `app.state.runs`, un registre
en memoire `{run_id: RunState}` cote process.

Evenements SSE emis :
- `run_started`  : `{"run_id": str}`
- `step`         : `{"executor_id": str, "context": SharedContext}`
- `approval_required` : `{"request": RemediationApprovalRequest}`
- `done`         : `{"approved": bool | null}`
- `error`        : `{"message": str}`
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from agent_framework import Workflow, WorkflowEvent
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.api.dependencies import persistence_dependency, settings_dependency
from src.api.sse import sse_event
from src.config import REPO_ROOT, Settings
from src.models import SharedContext
from src.orchestrator import build_workflow
from src.tools.persistence import IncidentRecord, PersistenceStore

router = APIRouter(tags=["runs"])

DEFAULT_LOG_PATH = REPO_ROOT / "data" / "payment-incident.log"


@dataclass
class RunState:
    """Etat en memoire d'une execution entre ses deux phases HTTP."""

    workflow: Workflow
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    pending_request_id: str | None = None


class ApprovalBody(BaseModel):
    """Corps de `POST /api/runs/{run_id}/approval`."""

    approved: bool


def _runs(request: Request) -> dict[str, RunState]:
    return request.app.state.runs  # type: ignore[no-any-return]


def _step_payload(event: WorkflowEvent[Any]) -> dict[str, Any]:
    context: SharedContext = event.data
    return {"executor_id": event.executor_id, "context": context.model_dump(mode="json")}


@router.post("/runs")
async def start_run(
    request: Request,
    settings: Settings = Depends(settings_dependency),
) -> StreamingResponse:
    """Demarre une nouvelle execution sur `data/payment-incident.log` (SSE)."""

    runs = _runs(request)
    run_id = uuid.uuid4().hex
    workflow = build_workflow(settings)
    raw_logs = DEFAULT_LOG_PATH.read_text(encoding="utf-8")
    state = RunState(workflow=workflow)
    runs[run_id] = state

    async def stream() -> AsyncIterator[str]:
        yield sse_event("run_started", {"run_id": run_id})
        try:
            result = workflow.run(SharedContext(raw_logs=raw_logs), stream=True)
            async for event in result:
                if event.type == "output":
                    yield sse_event("step", _step_payload(event))
                elif event.type == "request_info":
                    state.pending_request_id = event.request_id
                    yield sse_event("approval_required", {"request": event.data.model_dump(mode="json")})
            await result.get_final_response()
        except Exception as exc:  # noqa: BLE001 - on rapporte toute erreur au client SSE
            runs.pop(run_id, None)
            yield sse_event("error", {"message": str(exc)})
            return

        if state.pending_request_id is None:
            # Etat inattendu (le graphe se termine toujours sur la porte
            # HITL) : on nettoie quand meme le registre.
            runs.pop(run_id, None)
            yield sse_event("done", {"approved": None})

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/runs/{run_id}/approval")
async def submit_approval(
    run_id: str,
    body: ApprovalBody,
    request: Request,
    store: PersistenceStore = Depends(persistence_dependency),
) -> StreamingResponse:
    """Reprend l'execution `run_id` apres decision humaine (SSE)."""

    runs = _runs(request)
    state = runs.get(run_id)
    if state is None or state.pending_request_id is None:
        raise HTTPException(status_code=404, detail="Execution inconnue ou pas en attente de validation")

    request_id = state.pending_request_id

    async def stream() -> AsyncIterator[str]:
        final_context: SharedContext | None = None
        try:
            result = state.workflow.run(stream=True, responses={request_id: body.approved})
            async for event in result:
                if event.type == "output":
                    final_context = event.data
                    yield sse_event("step", _step_payload(event))
            await result.get_final_response()
        except Exception as exc:  # noqa: BLE001 - on rapporte toute erreur au client SSE
            runs.pop(run_id, None)
            yield sse_event("error", {"message": str(exc)})
            return

        runs.pop(run_id, None)
        if final_context is not None:
            await store.save(
                IncidentRecord(
                    id=run_id,
                    started_at=state.started_at,
                    finished_at=datetime.now(UTC),
                    approved=body.approved,
                    context=final_context,
                )
            )

        yield sse_event("done", {"approved": body.approved})

    return StreamingResponse(stream(), media_type="text/event-stream")
