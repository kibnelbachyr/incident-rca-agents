# Copyright (c) Microsoft. All rights reserved.

"""Executors for the orchestration graph (one per node, SPEC.md section 5).

Each executor wraps an agent (or, for `GatherEvidenceExecutor`, two
re-invoked agents) and updates the `SharedContext` that flows from node to
node via `ctx.send_message`. All "pipeline" executors also call
`ctx.yield_output(context)`: with `WorkflowBuilder(output_from="all")`, this
makes every agent output observable in the event stream (SPEC.md
acceptance criterion 7).

Agents remain stateless (SPEC.md section 2): it is the orchestrator (these
executors) that reads/writes the shared context between each call.
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
    """1st node: normalizes raw logs into a timeline/anomalies (agent 1/6)."""

    def __init__(self, agent: LogAnalyzerAgent, *, id: str = "log_analyzer") -> None:
        super().__init__(id=id)
        self._agent = agent

    @handler
    async def handle(self, context: SharedContext, ctx: WorkflowContext[SharedContext, SharedContext]) -> None:
        context.log_analysis = await self._agent.run(build_log_prompt(context.raw_logs))

        await ctx.yield_output(context)
        await ctx.send_message(context)


class IncidentExtractorExecutor(Executor):
    """2nd node: produces the structured incident object (agent 2/6)."""

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
    """3rd node: searches for precedents in the knowledge base (agent 3/6)."""

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
    """4th node: root cause hypothesis + confidence score (agent 4/6).

    Target of the conditional loop edge (SPEC.md section 5): the graph's
    `needs_more_evidence` function reads `context.root_cause.confiance`
    and `context.loop_count` (updated here and by `GatherEvidenceExecutor`)
    to decide between looping back or advancing to the HITL gate.
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
    """Step of the reflection loop (not a dedicated agent, DECISIONS.md #5).

    Re-invokes `LogAnalyzer` targeting the `preuves_manquantes` from the
    last `RootCause` pass, and refreshes `KBSearch`, before passing back
    into `RootCauseExecutor`. Increments `loop_count` (bounded by
    `MAX_REFLECTION_LOOPS`, checked by the graph).
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

        old_confidence = context.root_cause.confiance
        context.loop_count += 1

        missing = context.root_cause.preuves_manquantes
        missing_text = "; ".join(missing[:2]) if missing else "no specific targets"
        context.routing_note = (
            f"Confidence {old_confidence:.2f} below threshold — "
            f"targeted re-analysis initiated (loop {context.loop_count}). "
            f"Investigating: {missing_text}"
        )

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
    """HITL gate (SPEC.md section 5): suspends the graph via
    `ctx.request_info` until a boolean approval is received.

    `RemediationApprovalRequest` carries only a subset of the context; the
    full `SharedContext` is kept on the instance (DECISIONS.md #13) while
    waiting for the caller to respond via `workflow.run(responses={...})`,
    since the graph and its executors persist between the two `run` calls.
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
        del original_request  # the full context lives on self._context (see class docstring)

        context = self._context
        assert context is not None

        context.approved = response
        if response:
            await ctx.send_message(context)
        else:
            # Human rejection: we stop here (DECISIONS.md #14), no
            # remediation plan is generated or displayed.
            await ctx.yield_output(context)


class RemediationExecutor(Executor):
    """5th node: prioritized remediation plan, invoked only after human
    approval (agent 5/6). Plan is displayed only, never executed
    (CLAUDE.md - constraints not to bypass)."""

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
    """6th and last node: writes the final report (agent 6/6)."""

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
