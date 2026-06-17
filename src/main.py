# Copyright (c) Microsoft. All rights reserved.

"""Point d'entree CLI de la demo (SPEC.md section 9, etape 5).

Usage::

    python -m src.main --logs data/payment-incident.log

Injecte les logs dans le workflow d'orchestration (`src.orchestrator.build_workflow`)
et streame les evenements (`workflow.run(message, stream=True)`) : la sortie de
chaque agent est affichee des qu'elle est produite (SPEC.md critere
d'acceptation 7), y compris la boucle de reflexion `RootCause <-> GatherEvidence`
(critere 3/8).

A la porte HITL (`request_info`, critere 5), la demo affiche la synthese de
l'incident et de la cause racine retenue, puis demande une validation o/n sur
l'entree standard avant de reprendre le workflow (`responses={request_id: bool}`).
Sans approbation, aucun plan de remediation n'est genere ni affiche
(critere 6 / DECISIONS.md #15).
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from agent_framework import WorkflowEvent

from src.config import Settings, get_settings
from src.models import (
    Incident,
    IncidentReport,
    KBMatches,
    LogAnalysis,
    RemediationApprovalRequest,
    RemediationPlan,
    RootCauseHypothesis,
    SharedContext,
)
from src.observability import configure_observability
from src.orchestrator import build_workflow
from src.scenarios import DEFAULT_SCENARIO, SCENARIOS, get_scenario

SEPARATOR = "=" * 78

_STEP_TITLES: dict[str, str] = {
    "log_analyzer": "Agent 1/6 - LogAnalyzer : analyse des logs bruts",
    "incident_extractor": "Agent 2/6 - IncidentExtractor : extraction de l'incident",
    "kb_search": "Agent 3/6 - KBSearch : recherche de precedents",
    "root_cause": "Agent 4/6 - RootCause : hypothese de cause racine",
    "gather_evidence": "Boucle de reflexion - GatherEvidence : collecte de preuves complementaires",
    "remediation": "Agent 5/6 - Remediation : plan de remediation (propose)",
    "summary": "Agent 6/6 - Summary : rapport final",
    "human_approval": "Validation humaine : remediation refusee",
}


def _print_header(title: str) -> None:
    print()
    print(SEPARATOR)
    print(title)
    print(SEPARATOR)


def _print_log_analysis(data: LogAnalysis) -> None:
    print("Timeline reconstituee :")
    for event in data.timeline:
        print(f"  - {event.time}  {event.event}")
    print("Anomalies detectees :")
    for anomaly in data.anomalies:
        print(f"  - {anomaly}")
    print("Evenements correles :")
    for item in data.correlated_events:
        print(f"  - {item}")


def _print_incident(data: Incident) -> None:
    print(f"Titre     : {data.titre}")
    print(f"Severite  : {data.severite}")
    print(f"Services  : {', '.join(data.services)}")
    print(f"Fenetre   : {data.fenetre}")
    print("Symptomes :")
    for symptome in data.symptomes:
        print(f"  - {symptome}")


def _print_kb_matches(data: KBMatches) -> None:
    if not data.matches:
        print("Aucun precedent trouve dans la base de connaissances.")
        return
    print("Precedents trouves :")
    for match in data.matches:
        print(f"  - {match.id}  (similarite={match.similarite:.2f})")
        print(f"    -> resolution : {match.resolution}")


def _print_root_cause(data: RootCauseHypothesis, settings: Settings, *, loop_count: int) -> None:
    print(f"Cause retenue : {data.cause}")
    print(f"Raisonnement  : {data.raisonnement}")
    print(f"Confiance     : {data.confiance:.2f}  (seuil = {settings.confidence_threshold})")
    if data.confiance < settings.confidence_threshold:
        print(
            f"-> Confiance sous le seuil : l'orchestrateur reboucle pour "
            f"chercher des preuves (passage {loop_count + 1}/{settings.max_reflection_loops})."
        )
        print("Preuves manquantes a collecter :")
        for preuve in data.preuves_manquantes:
            print(f"  - {preuve}")
    else:
        print("-> Confiance suffisante : l'orchestrateur passe a la validation humaine.")


def _print_gather_evidence(context: SharedContext, settings: Settings) -> None:
    assert context.log_analysis is not None
    print(f"Reboucle {context.loop_count}/{settings.max_reflection_loops} : LogAnalyzer et KBSearch re-sollicites.")
    print("Nouveaux evenements correles :")
    for item in context.log_analysis.correlated_events:
        print(f"  - {item}")
    if context.kb_matches is not None and context.kb_matches.matches:
        precedents = ", ".join(match.id for match in context.kb_matches.matches)
        print(f"Base de connaissances reconfrontee : {precedents}")


def _print_remediation(data: RemediationPlan) -> None:
    print("Immediat :")
    for item in data.immediat:
        print(f"  - {item}")
    print("Court terme :")
    for item in data.court_terme:
        print(f"  - {item}")
    print("Long terme :")
    for item in data.long_terme:
        print(f"  - {item}")


def _print_report(data: IncidentReport) -> None:
    print(data.texte)


def _print_step_output(executor_id: str, context: SharedContext, settings: Settings) -> None:
    _print_header(_STEP_TITLES.get(executor_id, executor_id))

    if executor_id == "log_analyzer":
        assert context.log_analysis is not None
        _print_log_analysis(context.log_analysis)
    elif executor_id == "incident_extractor":
        assert context.incident is not None
        _print_incident(context.incident)
    elif executor_id == "kb_search":
        assert context.kb_matches is not None
        _print_kb_matches(context.kb_matches)
    elif executor_id == "root_cause":
        assert context.root_cause is not None
        _print_root_cause(context.root_cause, settings, loop_count=context.loop_count)
    elif executor_id == "gather_evidence":
        _print_gather_evidence(context, settings)
    elif executor_id == "remediation":
        assert context.remediation_plan is not None
        _print_remediation(context.remediation_plan)
    elif executor_id == "summary":
        assert context.report is not None
        print()
        _print_report(context.report)
    elif executor_id == "human_approval":
        print("L'humain a refuse la remediation : le workflow s'arrete ici.")
        print("Aucun plan de remediation n'est genere ni affiche (CLAUDE.md).")


def _ask_approval(request: RemediationApprovalRequest) -> bool:
    _print_header("Validation humaine requise avant remediation")
    print(f"Incident       : {request.incident.titre} ({request.incident.severite})")
    print(f"Services       : {', '.join(request.incident.services)}")
    print(f"Cause retenue  : {request.root_cause.cause}")
    print(f"Confiance      : {request.root_cause.confiance:.2f}")
    if request.kb_matches.matches:
        precedents = ", ".join(match.id for match in request.kb_matches.matches)
        print(f"Precedents lies : {precedents}")
    print()
    print(request.message)
    print("Rappel : la remediation reste un plan affiche, aucune action n'est executee (CLAUDE.md).")

    try:
        answer = input("Approuver le passage a la remediation ? [o/N] : ")
    except EOFError:
        print("(entree non interactive : refus par defaut)")
        return False

    return answer.strip().lower() in {"o", "oui", "y", "yes"}


async def run_demo(log_path: Path, *, scenario: str = DEFAULT_SCENARIO) -> None:
    settings = get_settings()
    configure_observability(settings)
    workflow = build_workflow(settings, scenario=scenario)
    raw_logs = log_path.read_text(encoding="utf-8")

    _print_header("DEMO - Diagnostic multi-agents d'un incident de paiement")
    print(f"Scenario               : {scenario}")
    print(f"Logs source           : {log_path}")
    print(f"Seuil de confiance    : {settings.confidence_threshold}")
    print(f"Boucles de reflexion max : {settings.max_reflection_loops}")
    print(f"Base de connaissances : {settings.kb_mode}")
    print(f"Modeles               : {'Azure OpenAI' if settings.use_real_azure_openai else 'StubChatClient (hors ligne)'}")

    pending_request: WorkflowEvent | None = None

    stream = workflow.run(SharedContext(raw_logs=raw_logs), stream=True)
    async for event in stream:
        if event.type == "output":
            _print_step_output(event.executor_id, event.data, settings)
        elif event.type == "request_info":
            pending_request = event
    await stream.get_final_response()

    if pending_request is None:
        _print_header("FIN")
        print("Le workflow s'est termine sans demander de validation humaine (etat inattendu).")
        return

    approved = _ask_approval(pending_request.data)

    stream = workflow.run(stream=True, responses={pending_request.request_id: approved})
    async for event in stream:
        if event.type == "output":
            _print_step_output(event.executor_id, event.data, settings)
    await stream.get_final_response()

    _print_header("FIN")
    if approved:
        print("Demo terminee : rapport final affiche ci-dessus.")
    else:
        print("Demo terminee : remediation non executee (refus humain).")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Demo d'analyse multi-agents d'un incident de paiement.")
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIOS),
        default=DEFAULT_SCENARIO,
        help="Scenario de demo a executer (defaut : %(default)s).",
    )
    parser.add_argument(
        "--logs",
        type=Path,
        default=None,
        help="Chemin du fichier de logs a injecter (defaut : logs du scenario choisi via --scenario).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    scenario_def = get_scenario(args.scenario)
    log_path = args.logs if args.logs is not None else scenario_def.log_path
    asyncio.run(run_demo(log_path, scenario=scenario_def.id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
