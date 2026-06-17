# Copyright (c) Microsoft. All rights reserved.

"""Test de bout en bout de l'API FastAPI (SSE + HITL + historique).

Memes garanties que `tests/orchestrator/test_workflow.py` (boucle de
reflexion visible, pause HITL, refus = pas de remediation), mais via les
endpoints HTTP (`POST /api/runs`, `POST /api/runs/{run_id}/approval`,
`GET /api/history`).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from src.api.app import create_app
from src.api.dependencies import persistence_dependency
from src.tools.persistence import LocalPersistenceStore


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[persistence_dependency] = lambda: LocalPersistenceStore(tmp_path)
    with TestClient(app) as test_client:
        yield test_client


def _read_sse(response: Response) -> list[tuple[str, Any]]:
    """Parse un flux `text/event-stream` en liste `(event, data)`."""

    events: list[tuple[str, Any]] = []
    event_name: str | None = None
    for line in response.iter_lines():
        if line == "":
            continue
        if line.startswith("event:"):
            event_name = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            assert event_name is not None
            events.append((event_name, json.loads(line.removeprefix("data:").strip())))
    return events


def test_run_then_approve_streams_steps_and_persists_report(client: TestClient) -> None:
    with client.stream("POST", "/api/runs") as response:
        assert response.status_code == 200
        events = _read_sse(response)

    assert events[0][0] == "run_started"
    run_id = events[0][1]["run_id"]

    step_executors = [data["executor_id"] for name, data in events if name == "step"]
    # Critere 3/8 : la boucle de reflexion est visible (2 passages RootCause).
    assert step_executors.count("root_cause") == 2
    assert "gather_evidence" in step_executors

    approval_events = [data for name, data in events if name == "approval_required"]
    assert len(approval_events) == 1
    request = approval_events[0]["request"]
    assert request["root_cause"]["confiance"] >= 0.75
    assert request["root_cause"]["preuves_manquantes"] == []

    # Pas de "done" cote phase 1 : le workflow est en pause HITL.
    assert "done" not in {name for name, _ in events}

    with client.stream("POST", f"/api/runs/{run_id}/approval", json={"approved": True}) as response:
        assert response.status_code == 200
        events2 = _read_sse(response)

    step_executors_2 = [data["executor_id"] for name, data in events2 if name == "step"]
    assert step_executors_2 == ["remediation", "summary"]

    done_events = [data for name, data in events2 if name == "done"]
    assert done_events == [{"approved": True}]

    history = client.get("/api/history").json()
    assert len(history) == 1
    assert history[0]["id"] == run_id
    assert history[0]["approved"] is True
    assert history[0]["severite"] == "SEV-1"

    record = client.get(f"/api/history/{run_id}").json()
    assert record["context"]["report"]["titre"].startswith("INCIDENT SEV-1")
    assert record["context"]["remediation_plan"]["immediat"]


def test_rejection_path_yields_no_remediation_and_persists(client: TestClient) -> None:
    with client.stream("POST", "/api/runs") as response:
        events = _read_sse(response)
    run_id = events[0][1]["run_id"]

    with client.stream("POST", f"/api/runs/{run_id}/approval", json={"approved": False}) as response:
        events2 = _read_sse(response)

    steps = [data for name, data in events2 if name == "step"]
    assert [step["executor_id"] for step in steps] == ["human_approval"]
    assert steps[0]["context"]["approved"] is False
    assert steps[0]["context"]["remediation_plan"] is None
    assert steps[0]["context"]["report"] is None

    done_events = [data for name, data in events2 if name == "done"]
    assert done_events == [{"approved": False}]

    history = client.get("/api/history").json()
    assert history[0]["approved"] is False


def test_approval_for_unknown_run_returns_404(client: TestClient) -> None:
    response = client.post("/api/runs/does-not-exist/approval", json={"approved": True})
    assert response.status_code == 404


def test_meta_and_health(client: TestClient) -> None:
    meta = client.get("/api/meta").json()
    assert meta["kb_mode"] == "local"
    assert meta["use_real_azure_openai"] is False
    assert meta["cosmos_enabled"] is False
    assert meta["confidence_threshold"] == pytest.approx(0.75)
    assert meta["max_reflection_loops"] == 2

    assert client.get("/api/health").json() == {"status": "ok"}


def test_history_record_not_found(client: TestClient) -> None:
    response = client.get("/api/history/does-not-exist")
    assert response.status_code == 404


def test_get_scenarios_lists_both_demo_scenarios(client: TestClient) -> None:
    response = client.get("/api/scenarios")
    assert response.status_code == 200
    body = response.json()

    assert body["default"] == "db_pool"
    ids = {s["id"] for s in body["scenarios"]}
    assert ids == {"db_pool", "paypal_integration"}
    for scenario in body["scenarios"]:
        assert scenario["label"]
        assert scenario["description"]


def test_start_run_with_unknown_scenario_returns_400(client: TestClient) -> None:
    response = client.post("/api/runs", json={"scenario": "does-not-exist"})
    assert response.status_code == 400


def test_run_paypal_scenario_streams_reflection_loop_and_persists_report(client: TestClient) -> None:
    with client.stream("POST", "/api/runs", json={"scenario": "paypal_integration"}) as response:
        assert response.status_code == 200
        events = _read_sse(response)

    assert events[0][0] == "run_started"
    run_id = events[0][1]["run_id"]

    step_executors = [data["executor_id"] for name, data in events if name == "step"]
    assert step_executors.count("root_cause") == 2
    assert "gather_evidence" in step_executors

    approval_events = [data for name, data in events if name == "approval_required"]
    assert len(approval_events) == 1
    request = approval_events[0]["request"]
    assert request["incident"]["severite"] == "SEV-2"
    assert request["root_cause"]["confiance"] >= 0.75
    assert request["root_cause"]["preuves_manquantes"] == []

    with client.stream("POST", f"/api/runs/{run_id}/approval", json={"approved": True}) as response:
        assert response.status_code == 200
        events2 = _read_sse(response)

    step_executors_2 = [data["executor_id"] for name, data in events2 if name == "step"]
    assert step_executors_2 == ["remediation", "summary"]

    done_events = [data for name, data in events2 if name == "done"]
    assert done_events == [{"approved": True}]

    record = client.get(f"/api/history/{run_id}").json()
    assert record["context"]["report"]["confiance"] == pytest.approx(0.93)
    assert "INC-241" in record["context"]["report"]["precedent_lie"]
