# Copyright (c) Microsoft. All rights reserved.

"""Workflow execution endpoints (SSE) - the core of the API.

The diagnosis proceeds in two HTTP phases, each an SSE stream
(`text/event-stream`):

1. `POST /api/runs`: creates a new run (a `Workflow` via
   `build_workflow`, DECISIONS.md #16) and streams `step` (output of each
   agent, including the `RootCause <-> GatherEvidence` loop) until the
   human gate (`approval_required`) or the end (`done`).
2. `POST /api/runs/{run_id}/approval`: resumes the SAME `Workflow` (`responses=
   {request_id: bool}`, DECISIONS.md #14) and streams the rest (refusal =
   `human_approval` only; approval = `remediation` + `summary`), then
   persists the final `SharedContext` (`src/tools/persistence.py`) and emits
   `done`.

The phase-1 `Workflow` must stay in memory until the approval call is made
(its executors, notably `HumanApprovalExecutor`, carry state -
DECISIONS.md #14): it is kept in `app.state.runs`, an in-memory
`{run_id: RunState}` registry on the process side.

SSE events emitted:
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
from src.config import Settings
from src.models import SharedContext
from src.orchestrator import build_workflow
from src.scenarios import get_scenario
from src.tools.persistence import IncidentRecord, PersistenceStore

router = APIRouter(tags=["runs"])


@dataclass
class RunState:
    """In-memory state of a run between its two HTTP phases."""

    workflow: Workflow
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    pending_request_id: str | None = None


class StartRunBody(BaseModel):
    """Optional body of `POST /api/runs`. No body = default scenario."""

    scenario: str | None = None


class ApprovalBody(BaseModel):
    """Body of `POST /api/runs/{run_id}/approval`."""

    approved: bool


def _runs(request: Request) -> dict[str, RunState]:
    return request.app.state.runs  # type: ignore[no-any-return]


def _step_payload(event: WorkflowEvent[Any]) -> dict[str, Any]:
    context: SharedContext = event.data
    return {"executor_id": event.executor_id, "context": context.model_dump(mode="json")}


@router.post("/runs")
async def start_run(
    request: Request,
    body: StartRunBody | None = None,
    settings: Settings = Depends(settings_dependency),
) -> StreamingResponse:
    """Start a new run on the requested scenario (SSE).

    `body.scenario` is resolved via `src.scenarios.get_scenario`; no body
    or no `scenario` field -> default scenario (`db_pool`).
    """

    try:
        scenario_def = get_scenario(body.scenario if body else None)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    runs = _runs(request)
    run_id = uuid.uuid4().hex
    workflow = build_workflow(settings, scenario=scenario_def.id)
    raw_logs = scenario_def.log_path.read_text(encoding="utf-8")
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
        except Exception as exc:  # noqa: BLE001 - report any error to the SSE client
            runs.pop(run_id, None)
            yield sse_event("error", {"message": str(exc)})
            return

        if state.pending_request_id is None:
            # Unexpected state (the graph always ends at the HITL gate):
            # clean up the registry anyway.
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
    """Resume run `run_id` after the human decision (SSE)."""

    runs = _runs(request)
    state = runs.get(run_id)
    if state is None or state.pending_request_id is None:
        raise HTTPException(status_code=404, detail="Run not found or not awaiting approval")

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
        except Exception as exc:  # noqa: BLE001 - report any error to the SSE client
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
