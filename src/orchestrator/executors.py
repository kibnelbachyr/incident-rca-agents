# Copyright (c) Microsoft. All rights reserved.

"""Executeurs du graphe d'orchestration (un par noeud, SPEC.md section 5).

Chaque executeur enveloppe un agent (ou, pour `GatherEvidenceExecutor`, deux
agents reinvoques) et met a jour le `SharedContext` qui circule de noeud en
noeud via `ctx.send_message`. Tous les executeurs "pipeline" appellent aussi
`ctx.yield_output(context)` : avec `WorkflowBuilder(output_from="all")`, cela
rend chaque sortie d'agent observable dans le flux d'evenements (SPEC.md
critere d'acceptation 7).

Les agents restent sans etat (SPEC.md section 2) : c'est l'orchestrateur (ces
executeurs) qui lit/ecrit le contexte partage entre chaque appel.
"""

from typing import Never

from agent_framework import Executor, WorkflowContext, handler, response_handler

from src.agents.incident_extractor import IncidentExtractorAgent
from src.agents.incident_extractor import build_prompt as build_incident_prompt
from src.agents.kb_search import KBSearchAgent
from src.agents.log_analyzer import LogAnalyzerAgent
from src.agents.log_analyzer import build_prompt as build_log_prompt
from src.agents.remediation import RemediationAgent
from src.agents.remediation import build_prompt as build_remediation_prompt
from src.agents.root_cause import RootCauseAgent
from src.agents.root_cause import build_prompt as build_root_cause_prompt
from src.agents.summary import SummaryAgent
from src.agents.summary import build_prompt as build_summary_prompt
from src.models import RemediationApprovalRequest, SharedContext


class LogAnalyzerExecutor(Executor):
    """1er noeud : normalise les logs bruts en timeline/anomalies (agent 1/6)."""

    def __init__(self, agent: LogAnalyzerAgent, *, id: str = "log_analyzer") -> None:
        super().__init__(id=id)
        self._agent = agent

    @handler
    async def handle(self, context: SharedContext, ctx: WorkflowContext[SharedContext, SharedContext]) -> None:
        context.log_analysis = await self._agent.run(build_log_prompt(context.raw_logs))

        await ctx.yield_output(context)
        await ctx.send_message(context)


class IncidentExtractorExecutor(Executor):
    """2e noeud : produit l'objet incident structure (agent 2/6)."""

    def __init__(self, agent: IncidentExtractorAgent, *, id: str = "incident_extractor") -> None:
        super().__init__(id=id)
        self._agent = agent

    @handler
    async def handle(self, context: SharedContext, ctx: WorkflowContext[SharedContext, SharedContext]) -> None:
        assert context.log_analysis is not None

        context.incident = await self._agent.run(build_incident_prompt(context.log_analysis))

        await ctx.yield_output(context)
        await ctx.send_message(context)


class KBSearchExecutor(Executor):
    """3e noeud : recherche de precedents dans la base de connaissances (agent 3/6)."""

    def __init__(self, agent: KBSearchAgent, *, id: str = "kb_search") -> None:
        super().__init__(id=id)
        self._agent = agent

    @handler
    async def handle(self, context: SharedContext, ctx: WorkflowContext[SharedContext, SharedContext]) -> None:
        assert context.incident is not None

        context.kb_matches = await self._agent.run(context.incident)

        await ctx.yield_output(context)
        await ctx.send_message(context)


class RootCauseExecutor(Executor):
    """4e noeud : hypothese de cause racine + score de confiance (agent 4/6).

    Cible de l'arete conditionnelle de boucle (SPEC.md section 5) : la
    fonction `needs_more_evidence` du graphe lit `context.root_cause.confiance`
    et `context.loop_count` (mis a jour ici et par `GatherEvidenceExecutor`)
    pour decider entre reboucler ou avancer vers la porte HITL.
    """

    def __init__(self, agent: RootCauseAgent, *, id: str = "root_cause") -> None:
        super().__init__(id=id)
        self._agent = agent

    @handler
    async def handle(self, context: SharedContext, ctx: WorkflowContext[SharedContext, SharedContext]) -> None:
        assert context.incident is not None
        assert context.log_analysis is not None
        assert context.kb_matches is not None

        hypothesis = await self._agent.run(
            build_root_cause_prompt(
                context.incident,
                context.log_analysis,
                context.kb_matches,
                evidence_log=context.evidence_log or None,
            )
        )
        context.root_cause = hypothesis
        context.root_cause_history.append(hypothesis)

        await ctx.yield_output(context)
        await ctx.send_message(context)


class GatherEvidenceExecutor(Executor):
    """Etape de la boucle de reflexion (pas un agent dedie, DECISIONS.md #5).

    Reinvoque `LogAnalyzer` en ciblant les `preuves_manquantes` du dernier
    passage de `RootCause`, et rafraichit `KBSearch`, avant de repasser dans
    `RootCauseExecutor`. Incremente `loop_count` (borne par
    `MAX_REFLECTION_LOOPS`, verifiee par le graphe).
    """

    def __init__(
        self,
        log_analyzer: LogAnalyzerAgent,
        kb_search: KBSearchAgent,
        *,
        id: str = "gather_evidence",
    ) -> None:
        super().__init__(id=id)
        self._log_analyzer = log_analyzer
        self._kb_search = kb_search

    @handler
    async def handle(self, context: SharedContext, ctx: WorkflowContext[SharedContext, SharedContext]) -> None:
        assert context.root_cause is not None

        context.loop_count += 1

        log_analysis = await self._log_analyzer.run(
            build_log_prompt(context.raw_logs, focus=context.root_cause.preuves_manquantes)
        )
        context.log_analysis = log_analysis
        context.evidence_log.extend(log_analysis.correlated_events)

        if context.incident is not None:
            context.kb_matches = await self._kb_search.run(context.incident)

        await ctx.yield_output(context)
        await ctx.send_message(context)


class HumanApprovalExecutor(Executor):
    """Porte HITL (SPEC.md section 5) : suspend le graphe via
    `ctx.request_info` jusqu'a reception d'une approbation booleenne.

    `RemediationApprovalRequest` ne porte qu'un sous-ensemble du contexte ; le
    `SharedContext` complet est garde sur l'instance (DECISIONS.md #13) le
    temps que l'appelant reponde via `workflow.run(responses={...})`, le
    graphe et ses executeurs persistant entre les deux appels `run`.
    """

    def __init__(self, *, id: str = "human_approval") -> None:
        super().__init__(id=id)
        self._context: SharedContext | None = None

    @handler
    async def handle(self, context: SharedContext, ctx: WorkflowContext[SharedContext, SharedContext]) -> None:
        assert context.incident is not None
        assert context.root_cause is not None
        assert context.kb_matches is not None

        self._context = context
        request = RemediationApprovalRequest(
            incident=context.incident,
            root_cause=context.root_cause,
            kb_matches=context.kb_matches,
        )
        await ctx.request_info(request, response_type=bool)

    @response_handler
    async def handle_response(
        self,
        original_request: RemediationApprovalRequest,
        response: bool,
        ctx: WorkflowContext[SharedContext, SharedContext],
    ) -> None:
        del original_request  # le contexte complet est sur self._context (cf. docstring de classe)

        context = self._context
        assert context is not None

        context.approved = response
        if response:
            await ctx.send_message(context)
        else:
            # Refus humain : on s'arrete ici (DECISIONS.md #14), aucun plan de
            # remediation n'est genere ni affiche.
            await ctx.yield_output(context)


class RemediationExecutor(Executor):
    """5e noeud : plan de remediation priorise, invoque uniquement apres
    approbation humaine (agent 5/6). Plan affiche uniquement, jamais execute
    (CLAUDE.md - contraintes a ne pas contourner)."""

    def __init__(self, agent: RemediationAgent, *, id: str = "remediation") -> None:
        super().__init__(id=id)
        self._agent = agent

    @handler
    async def handle(self, context: SharedContext, ctx: WorkflowContext[SharedContext, SharedContext]) -> None:
        assert context.incident is not None
        assert context.root_cause is not None
        assert context.kb_matches is not None

        context.remediation_plan = await self._agent.run(
            build_remediation_prompt(context.incident, context.root_cause, context.kb_matches)
        )

        await ctx.yield_output(context)
        await ctx.send_message(context)


class SummaryExecutor(Executor):
    """6e et dernier noeud : redige le rapport final (agent 6/6)."""

    def __init__(self, agent: SummaryAgent, *, id: str = "summary") -> None:
        super().__init__(id=id)
        self._agent = agent

    @handler
    async def handle(self, context: SharedContext, ctx: WorkflowContext[Never, SharedContext]) -> None:
        assert context.incident is not None
        assert context.log_analysis is not None
        assert context.root_cause is not None
        assert context.remediation_plan is not None
        assert context.kb_matches is not None

        context.report = await self._agent.run(
            build_summary_prompt(
                context.incident,
                context.log_analysis,
                context.root_cause,
                context.remediation_plan,
                context.kb_matches,
            )
        )

        await ctx.yield_output(context)
