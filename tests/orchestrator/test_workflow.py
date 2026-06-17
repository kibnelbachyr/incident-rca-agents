# Copyright (c) Microsoft. All rights reserved.

"""Test du graphe d'orchestration complet (SPEC.md section 5).

Couvre les 8 criteres d'acceptation de SPEC.md section 8 sur
`data/payment-incident.log`, en mode hors-ligne (`StubChatClient`) :

1. `IncidentExtractor` -> incident SEV-1 sur `payment-api` / `db-pool`.
2. `KBSearch` -> deux precedents (`INC-204`, `INC-187`).
3. 1er passage `RootCause` : confiance < 0.75 -> reboucle (visible dans le flux).
4. 2e passage `RootCause` : confiance >= 0.75, cause = `max_pool_size`.
5. Pause HITL avant remediation (`request_info` / `IDLE_WITH_PENDING_REQUESTS`).
6. Apres approbation : `RemediationPlan` puis rapport final.
7. Chaque sortie d'agent est observable (evenements `type="output"`).
8. La boucle ne depasse jamais `MAX_REFLECTION_LOOPS`.
"""

from __future__ import annotations

from pathlib import Path

from src.config import get_settings
from src.models import SharedContext
from src.orchestrator import build_workflow

RAW_LOGS = (Path(__file__).resolve().parent.parent.parent / "data" / "payment-incident.log").read_text(
    encoding="utf-8"
)

PAYPAL_RAW_LOGS = (
    Path(__file__).resolve().parent.parent.parent / "data" / "payment-paypal-incident.log"
).read_text(encoding="utf-8")


def _output_steps(result: list) -> list[tuple[str, SharedContext]]:
    return [(event.executor_id, event.data) for event in result if event.type == "output"]


async def test_workflow_reflects_then_pauses_for_human_approval() -> None:
    settings = get_settings()
    workflow = build_workflow(settings)

    result = await workflow.run(SharedContext(raw_logs=RAW_LOGS))

    steps = _output_steps(result)
    step_ids = [executor_id for executor_id, _ in steps]

    # Critere 1 : incident SEV-1 sur payment-api / db-pool.
    incident = dict(steps)["incident_extractor"].incident
    assert incident is not None
    assert incident.severite == "SEV-1"
    assert "payment-api" in incident.services
    assert "db-pool" in incident.services

    # Critere 2 : deux precedents KB.
    kb_matches = dict(steps)["kb_search"].kb_matches
    assert kb_matches is not None
    assert {match.id for match in kb_matches.matches} == {"INC-204", "INC-187"}

    # Critere 3 : 1er passage RootCause sous le seuil -> reboucle visible.
    # (SharedContext est mute en place : `data` reference le meme objet final
    # pour toutes les sorties, donc seul `root_cause_history` (liste accumulee
    # via .append()) garde les deux passages distincts apres coup.)
    final_context = steps[-1][1]
    root_cause_history = final_context.root_cause_history
    assert len(root_cause_history) == 2
    assert root_cause_history[0].confiance < settings.confidence_threshold
    assert root_cause_history[0].preuves_manquantes
    assert "gather_evidence" in step_ids
    first_root_cause = step_ids.index("root_cause")
    gather_evidence = step_ids.index("gather_evidence")
    second_root_cause = step_ids.index("root_cause", gather_evidence + 1)
    assert first_root_cause < gather_evidence < second_root_cause

    # Critere 4 : 2e passage au-dessus du seuil, cause = max_pool_size, Stripe ecarte.
    assert root_cause_history[1].confiance >= settings.confidence_threshold
    assert "max_pool_size" in root_cause_history[1].cause
    assert root_cause_history[1].preuves_manquantes == []

    # Critere 5 : pause HITL avant remediation.
    assert result.get_final_state().value == "IDLE_WITH_PENDING_REQUESTS"
    request_events = result.get_request_info_events()
    assert len(request_events) == 1
    request = request_events[0].data
    assert request.incident == incident
    assert request.root_cause == root_cause_history[1]

    # Critere 7 : chaque agent a produit une sortie observable.
    assert step_ids == [
        "log_analyzer",
        "incident_extractor",
        "kb_search",
        "root_cause",
        "gather_evidence",
        "root_cause",
    ]

    # Critere 8 : la boucle ne depasse jamais MAX_REFLECTION_LOOPS.
    assert final_context.loop_count <= settings.max_reflection_loops
    assert step_ids.count("gather_evidence") <= settings.max_reflection_loops


async def test_workflow_resumes_after_approval_and_produces_report() -> None:
    settings = get_settings()
    workflow = build_workflow(settings)

    first = await workflow.run(SharedContext(raw_logs=RAW_LOGS))
    request_id = first.get_request_info_events()[0].request_id

    second = await workflow.run(responses={request_id: True})

    steps = _output_steps(second)
    step_ids = [executor_id for executor_id, _ in steps]

    # Critere 6 : RemediationPlan puis rapport final apres approbation.
    assert step_ids == ["remediation", "summary"]

    remediation_plan = dict(steps)["remediation"].remediation_plan
    assert remediation_plan is not None
    assert remediation_plan.immediat
    assert remediation_plan.court_terme
    assert remediation_plan.long_terme

    final_context = dict(steps)["summary"]
    assert final_context.approved is True
    report = final_context.report
    assert report is not None
    assert report.confiance == 0.88
    assert "INC-204" in (report.precedent_lie or "")
    assert "CAUSE RACINE" in report.texte
    assert "REMÉDIATION" in report.texte
    assert "PRÉCÉDENT LIÉ" in report.texte

    assert second.get_final_state().value == "IDLE"


async def test_workflow_stops_without_remediation_if_human_rejects() -> None:
    settings = get_settings()
    workflow = build_workflow(settings)

    first = await workflow.run(SharedContext(raw_logs=RAW_LOGS))
    request_id = first.get_request_info_events()[0].request_id

    second = await workflow.run(responses={request_id: False})

    outputs = second.get_outputs()
    assert len(outputs) == 1
    final_context = outputs[0]

    assert final_context.approved is False
    assert final_context.remediation_plan is None
    assert final_context.report is None
    assert second.get_final_state().value == "IDLE"


async def test_paypal_scenario_reflects_then_pauses_for_human_approval() -> None:
    """Meme garanties que ci-dessus, pour le scenario `paypal_integration`.

    Couvre la demande explicite de la demo : la 1ere hypothese de RootCause
    doit etre sous le seuil de confiance (deux hypotheses concurrentes,
    externe vs. interne) pour forcer le reboucle vers GatherEvidence, qui
    tranche en faveur de la regression interne (case-sensitive header lookup).
    """

    settings = get_settings()
    workflow = build_workflow(settings, scenario="paypal_integration")

    result = await workflow.run(SharedContext(raw_logs=PAYPAL_RAW_LOGS))

    steps = _output_steps(result)
    step_ids = [executor_id for executor_id, _ in steps]

    incident = dict(steps)["incident_extractor"].incident
    assert incident is not None
    assert incident.severite == "SEV-2"
    assert "payment-api" in incident.services
    assert "paypal-webhook" in incident.services

    kb_matches = dict(steps)["kb_search"].kb_matches
    assert kb_matches is not None
    assert {match.id for match in kb_matches.matches} == {"INC-241", "INC-223"}

    # 1er passage RootCause sous le seuil (hypotheses concurrentes) -> reboucle.
    final_context = steps[-1][1]
    root_cause_history = final_context.root_cause_history
    assert len(root_cause_history) == 2
    assert root_cause_history[0].confiance < settings.confidence_threshold
    assert root_cause_history[0].preuves_manquantes
    assert "gather_evidence" in step_ids
    first_root_cause = step_ids.index("root_cause")
    gather_evidence = step_ids.index("gather_evidence")
    second_root_cause = step_ids.index("root_cause", gather_evidence + 1)
    assert first_root_cause < gather_evidence < second_root_cause

    # 2e passage au-dessus du seuil, hypothese externe (PayPal) ecartee.
    assert root_cause_history[1].confiance >= settings.confidence_threshold
    assert "case-sensitive" in root_cause_history[1].cause
    assert root_cause_history[1].preuves_manquantes == []

    assert result.get_final_state().value == "IDLE_WITH_PENDING_REQUESTS"
    request_events = result.get_request_info_events()
    assert len(request_events) == 1
    request = request_events[0].data
    assert request.incident == incident
    assert request.root_cause == root_cause_history[1]

    assert step_ids == [
        "log_analyzer",
        "incident_extractor",
        "kb_search",
        "root_cause",
        "gather_evidence",
        "root_cause",
    ]

    assert final_context.loop_count <= settings.max_reflection_loops
    assert step_ids.count("gather_evidence") <= settings.max_reflection_loops


async def test_paypal_scenario_resumes_after_approval_and_produces_report() -> None:
    settings = get_settings()
    workflow = build_workflow(settings, scenario="paypal_integration")

    first = await workflow.run(SharedContext(raw_logs=PAYPAL_RAW_LOGS))
    request_id = first.get_request_info_events()[0].request_id

    second = await workflow.run(responses={request_id: True})

    steps = _output_steps(second)
    step_ids = [executor_id for executor_id, _ in steps]
    assert step_ids == ["remediation", "summary"]

    remediation_plan = dict(steps)["remediation"].remediation_plan
    assert remediation_plan is not None
    assert remediation_plan.immediat
    assert remediation_plan.court_terme
    assert remediation_plan.long_terme

    final_context = dict(steps)["summary"]
    assert final_context.approved is True
    report = final_context.report
    assert report is not None
    assert report.confiance == 0.93
    assert "INC-241" in (report.precedent_lie or "")
    assert "CAUSE RACINE" in report.texte or "ROOT CAUSE" in report.texte

    assert second.get_final_state().value == "IDLE"
