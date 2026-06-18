# Copyright (c) Microsoft. All rights reserved.

"""Demo CLI entry point (SPEC.md section 9, step 5).

Usage::

    python -m src.main --logs data/payment-incident.log

Feeds the logs into the orchestration workflow (`src.orchestrator.build_workflow`)
and streams the events (`workflow.run(message, stream=True)`): each agent's output
is printed as soon as it's produced (SPEC.md acceptance criterion 7), including the
reflection loop `RootCause <-> GatherEvidence` (criterion 3/8).

At the HITL gate (`request_info`, criterion 5), the demo prints the incident
summary and the selected root cause, then asks for a y/n approval on standard
input before resuming the workflow (`responses={request_id: bool}`).
Without approval, no remediation plan is generated or displayed
(criterion 6 / DECISIONS.md #15).
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
    "log_analyzer": "Agent 1/6 - LogAnalyzer: raw log analysis",
    "incident_extractor": "Agent 2/6 - IncidentExtractor: incident extraction",
    "kb_search": "Agent 3/6 - KBSearch: precedent search",
    "root_cause": "Agent 4/6 - RootCause: root cause hypothesis",
    "gather_evidence": "Reflection loop - GatherEvidence: collecting additional evidence",
    "remediation": "Agent 5/6 - Remediation: remediation plan (proposed)",
    "summary": "Agent 6/6 - Summary: final report",
    "human_approval": "Human approval: remediation declined",
}


def _print_header(title: str) -> None:
    print()
    print(SEPARATOR)
    print(title)
    print(SEPARATOR)


def _print_log_analysis(data: LogAnalysis) -> None:
    print("Reconstructed timeline:")
    for event in data.timeline:
        print(f"  - {event.time}  {event.event}")
    print("Detected anomalies:")
    for anomaly in data.anomalies:
        print(f"  - {anomaly}")
    print("Correlated events:")
    for item in data.correlated_events:
        print(f"  - {item}")


def _print_incident(data: Incident) -> None:
    print(f"Title    : {data.titre}")
    print(f"Severity : {data.severite}")
    print(f"Services : {', '.join(data.services)}")
    print(f"Window   : {data.fenetre}")
    print("Symptoms :")
    for symptome in data.symptomes:
        print(f"  - {symptome}")


def _print_kb_matches(data: KBMatches) -> None:
    if not data.matches:
        print("No precedent found in the knowledge base.")
        return
    print("Precedents found:")
    for match in data.matches:
        print(f"  - {match.id}  (similarity={match.similarite:.2f})")
        print(f"    -> resolution: {match.resolution}")


def _print_root_cause(data: RootCauseHypothesis, settings: Settings, *, loop_count: int) -> None:
    print(f"Selected cause : {data.cause}")
    print(f"Reasoning      : {data.raisonnement}")
    print(f"Confidence     : {data.confiance:.2f}  (threshold = {settings.confidence_threshold})")
    if data.confiance < settings.confidence_threshold:
        print(
            f"-> Confidence below threshold: the orchestrator loops back to "
            f"gather more evidence (pass {loop_count + 1}/{settings.max_reflection_loops})."
        )
        print("Missing evidence to collect:")
        for preuve in data.preuves_manquantes:
            print(f"  - {preuve}")
    else:
        print("-> Confidence sufficient: the orchestrator proceeds to human approval.")


def _print_gather_evidence(context: SharedContext, settings: Settings) -> None:
    assert context.log_analysis is not None
    print(f"Loop {context.loop_count}/{settings.max_reflection_loops}: LogAnalyzer and KBSearch re-invoked.")
    print("New correlated events:")
    for item in context.log_analysis.correlated_events:
        print(f"  - {item}")
    if context.kb_matches is not None and context.kb_matches.matches:
        precedents = ", ".join(match.id for match in context.kb_matches.matches)
        print(f"Knowledge base re-checked: {precedents}")


def _print_remediation(data: RemediationPlan) -> None:
    print("Immediate:")
    for item in data.immediat:
        print(f"  - {item}")
    print("Short term:")
    for item in data.court_terme:
        print(f"  - {item}")
    print("Long term:")
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
        print("The human declined remediation: the workflow stops here.")
        print("No remediation plan is generated or displayed (CLAUDE.md).")


def _ask_approval(request: RemediationApprovalRequest) -> bool:
    _print_header("Human approval required before remediation")
    print(f"Incident           : {request.incident.titre} ({request.incident.severite})")
    print(f"Services           : {', '.join(request.incident.services)}")
    print(f"Selected cause     : {request.root_cause.cause}")
    print(f"Confidence         : {request.root_cause.confiance:.2f}")
    if request.kb_matches.matches:
        precedents = ", ".join(match.id for match in request.kb_matches.matches)
        print(f"Related precedents : {precedents}")
    print()
    print(request.message)
    print("Reminder: remediation stays a displayed plan, no action is ever executed (CLAUDE.md).")

    try:
        answer = input("Approve proceeding to remediation? [y/N]: ")
    except EOFError:
        print("(non-interactive input: declined by default)")
        return False

    return answer.strip().lower() in {"y", "yes"}


async def run_demo(log_path: Path, *, scenario: str = DEFAULT_SCENARIO) -> None:
    settings = get_settings()
    configure_observability(settings)
    workflow = build_workflow(settings, scenario=scenario)
    raw_logs = log_path.read_text(encoding="utf-8")

    _print_header("DEMO - Multi-agent diagnosis of a payment incident")
    print(f"Scenario                : {scenario}")
    print(f"Source logs             : {log_path}")
    print(f"Confidence threshold    : {settings.confidence_threshold}")
    print(f"Max reflection loops    : {settings.max_reflection_loops}")
    print(f"Knowledge base          : {settings.kb_mode}")
    print(f"Models                  : {'Azure OpenAI' if settings.use_real_azure_openai else 'StubChatClient (offline)'}")

    pending_request: WorkflowEvent | None = None

    stream = workflow.run(SharedContext(raw_logs=raw_logs), stream=True)
    async for event in stream:
        if event.type == "output":
            _print_step_output(event.executor_id, event.data, settings)
        elif event.type == "request_info":
            pending_request = event
    await stream.get_final_response()

    if pending_request is None:
        _print_header("END")
        print("The workflow finished without requesting human approval (unexpected state).")
        return

    approved = _ask_approval(pending_request.data)

    stream = workflow.run(stream=True, responses={pending_request.request_id: approved})
    async for event in stream:
        if event.type == "output":
            _print_step_output(event.executor_id, event.data, settings)
    await stream.get_final_response()

    _print_header("END")
    if approved:
        print("Demo finished: final report displayed above.")
    else:
        print("Demo finished: remediation not executed (declined by human).")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Multi-agent payment incident analysis demo.")
    parser.add_argument(
        "--scenario",
        choices=sorted(SCENARIOS),
        default=DEFAULT_SCENARIO,
        help="Demo scenario to run (default: %(default)s).",
    )
    parser.add_argument(
        "--logs",
        type=Path,
        default=None,
        help="Path to the log file to inject (default: the chosen scenario's logs via --scenario).",
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
