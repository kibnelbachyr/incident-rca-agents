# Copyright (c) Microsoft. All rights reserved.

"""Data contracts (pydantic) exchanged between the orchestrator and the agents.

These models are the "source of truth" for the JSON schemas defined in
SPEC.md section 4. Each agent returns exclusively JSON valid against one of
these models (via `response_format` on the chat client side). The
orchestrator accumulates these outputs in `SharedContext`, which flows from
node to node in the `WorkflowBuilder` graph.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 1. LogAnalyzer -> LogAnalysis
# ---------------------------------------------------------------------------


class TimelineEvent(BaseModel):
    """A normalized event extracted from the raw logs."""

    time: str
    event: str


class LogAnalysis(BaseModel):
    """Output of the `LogAnalyzer` agent (SPEC.md section 4.1)."""

    timeline: list[TimelineEvent]
    anomalies: list[str]
    correlated_events: list[str]


# ---------------------------------------------------------------------------
# 2. IncidentExtractor -> Incident
# ---------------------------------------------------------------------------


class Incident(BaseModel):
    """Output of the `IncidentExtractor` agent (SPEC.md section 4.2)."""

    titre: str
    severite: str = Field(pattern=r"^SEV-[1-5]$")
    services: list[str]
    fenetre: str
    symptomes: list[str]


# ---------------------------------------------------------------------------
# 3. KBSearch -> KBMatches
# ---------------------------------------------------------------------------


class KBMatch(BaseModel):
    """A precedent returned by the knowledge base."""

    id: str
    similarite: float = Field(ge=0.0, le=1.0)
    resolution: str


class KBMatches(BaseModel):
    """Output of the `KBSearch` agent (SPEC.md section 4.3)."""

    matches: list[KBMatch] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 4. RootCause -> RootCauseHypothesis
# ---------------------------------------------------------------------------


class RootCauseHypothesis(BaseModel):
    """Output of the `RootCause` agent (SPEC.md section 4.4).

    If `confiance < CONFIDENCE_THRESHOLD`, `preuves_manquantes` must list
    what the orchestrator will go fetch (`GatherEvidence` loop).
    """

    cause: str
    raisonnement: str
    confiance: float = Field(ge=0.0, le=1.0)
    preuves_manquantes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 5. Remediation -> RemediationPlan (behind HITL)
# ---------------------------------------------------------------------------


class RemediationPlan(BaseModel):
    """Output of the `Remediation` agent (SPEC.md section 4.5).

    Proposed plan only: no action is ever executed on a real system.
    """

    immediat: list[str]
    court_terme: list[str]
    long_terme: list[str]


# ---------------------------------------------------------------------------
# 6. Summary -> IncidentReport
# ---------------------------------------------------------------------------


class IncidentReport(BaseModel):
    """Output of the `Summary` agent (SPEC.md section 4.6 / scenario section 5).

    `texte` carries the ready-to-paste report (scenario format); the other
    fields expose the key values for a structured display.
    """

    titre: str
    fenetre: str
    impact: str
    cause_racine: str
    confiance: float = Field(ge=0.0, le=1.0)
    remediation: list[str]
    precedent_lie: str | None = None
    texte: str


# ---------------------------------------------------------------------------
# Human-in-the-loop: approval gate before remediation
# ---------------------------------------------------------------------------


class RemediationApprovalRequest(BaseModel):
    """Data presented to the human before invoking the `Remediation` agent.

    Emitted via `ctx.request_info(request_data=..., response_type=bool)`;
    the workflow stays paused until a boolean response is received.
    """

    incident: Incident
    root_cause: RootCauseHypothesis
    kb_matches: KBMatches
    message: str = "Approve proceeding to remediation?"


# ---------------------------------------------------------------------------
# Shared context (orchestrator): grows as the graph progresses
# ---------------------------------------------------------------------------


class SharedContext(BaseModel):
    """Context held by the orchestrator and passed from node to node.

    Agents are stateless: they never read/write this context directly, it's
    the orchestrator (the `Executor`s) that updates it between each agent
    call.
    """

    raw_logs: str

    # Successive agent outputs.
    log_analysis: LogAnalysis | None = None
    incident: Incident | None = None
    kb_matches: KBMatches | None = None
    root_cause: RootCauseHypothesis | None = None
    remediation_plan: RemediationPlan | None = None
    report: IncidentReport | None = None

    # Reflection loop (bounded by MAX_REFLECTION_LOOPS).
    loop_count: int = 0
    root_cause_history: list[RootCauseHypothesis] = Field(default_factory=list)
    evidence_log: list[str] = Field(default_factory=list)

    # Human approval gate.
    approved: bool | None = None

    # Routing note set by GatherEvidenceExecutor.
    routing_note: str | None = None
