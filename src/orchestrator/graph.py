# Copyright (c) Microsoft. All rights reserved.

"""Construction du graphe `WorkflowBuilder` (SPEC.md section 5).

Topologie::

    LogAnalyzer -> IncidentExtractor -> KBSearch -> RootCause --[switch]--+
                          ^                                               |
                          | confiance < seuil ET loop_count < max         | sinon
                          +------------------ GatherEvidence <------------+
                                                                           v
                                                              HumanApproval (HITL)
                                                                           | approuve
                                                                           v
                                                          Remediation -> Summary

`needs_more_evidence` implemente l'arete conditionnelle de la boucle de
reflexion (bornee par `MAX_REFLECTION_LOOPS`) ; la porte HITL est geree par
`HumanApprovalExecutor` via `ctx.request_info`/`@response_handler`.
"""

from __future__ import annotations

from agent_framework import Case, Default, Workflow, WorkflowBuilder

from src.agents.clients import get_chat_client
from src.agents.incident_extractor import IncidentExtractorAgent
from src.agents.kb_search import KBSearchAgent
from src.agents.log_analyzer import LogAnalyzerAgent
from src.agents.remediation import RemediationAgent
from src.agents.root_cause import RootCauseAgent
from src.agents.summary import SummaryAgent
from src.config import Settings
from src.models import SharedContext
from src.orchestrator.executors import (
    GatherEvidenceExecutor,
    HumanApprovalExecutor,
    IncidentExtractorExecutor,
    KBSearchExecutor,
    LogAnalyzerExecutor,
    RemediationExecutor,
    RootCauseExecutor,
    SummaryExecutor,
)
from src.tools.knowledge_base import get_knowledge_base


def build_workflow(settings: Settings, *, scenario: str = "db_pool") -> Workflow:
    """Construit le workflow complet a partir des parametres d'orchestration.

    Modele "leger" pour les taches mecaniques (LogAnalyzer, IncidentExtractor,
    KBSearch, Summary) et "fort" pour RootCause/Remediation (CLAUDE.md,
    SPEC.md section 2). `LogAnalyzer` et `KBSearch` sont partages entre leur
    noeud de pipeline et `GatherEvidenceExecutor` pour que le compteur d'appels
    du `StubChatClient` (1er passage / 2e passage) soit coherent en mode hors-ligne.

    `scenario` selectionne le jeu de reponses canon rejoue par `StubChatClient`
    en mode hors-ligne (cf. `src.scenarios`) ; sans effet en mode Azure OpenAI reel.
    """

    light_client = get_chat_client(settings, light=True, scenario=scenario)
    strong_client = get_chat_client(settings, light=False, scenario=scenario)
    knowledge_base = get_knowledge_base(settings)

    log_analyzer_agent = LogAnalyzerAgent(light_client)
    kb_search_agent = KBSearchAgent(light_client, knowledge_base)

    log_analyzer = LogAnalyzerExecutor(log_analyzer_agent)
    incident_extractor = IncidentExtractorExecutor(IncidentExtractorAgent(light_client))
    kb_search = KBSearchExecutor(kb_search_agent)
    root_cause = RootCauseExecutor(RootCauseAgent(strong_client))
    gather_evidence = GatherEvidenceExecutor(log_analyzer_agent, kb_search_agent)
    human_approval = HumanApprovalExecutor()
    remediation = RemediationExecutor(RemediationAgent(strong_client))
    summary = SummaryExecutor(SummaryAgent(light_client))

    def needs_more_evidence(context: SharedContext) -> bool:
        assert context.root_cause is not None
        return (
            context.root_cause.confiance < settings.confidence_threshold
            and context.loop_count < settings.max_reflection_loops
        )

    return (
        WorkflowBuilder(start_executor=log_analyzer, output_from="all")
        .add_edge(log_analyzer, incident_extractor)
        .add_edge(incident_extractor, kb_search)
        .add_edge(kb_search, root_cause)
        .add_switch_case_edge_group(
            root_cause,
            [
                Case(condition=needs_more_evidence, target=gather_evidence),
                Default(target=human_approval),
            ],
        )
        .add_edge(gather_evidence, root_cause)
        .add_edge(human_approval, remediation)
        .add_edge(remediation, summary)
        .build()
    )
