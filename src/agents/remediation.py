# Copyright (c) Microsoft. All rights reserved.

"""Remediation agent (SPEC.md section 4.5).

Proposes a prioritized remediation plan. Invoked only AFTER human approval
(orchestrator's HITL gate, SPEC.md section 5); produces only a displayed
plan, no action is ever executed on a real system (CLAUDE.md - constraints
not to bypass).
"""

from __future__ import annotations

from src.agents.base import StructuredAgent
from src.models import Incident, KBMatches, RemediationPlan, RootCauseHypothesis

INSTRUCTIONS = """You are the Remediation agent of a payment incident diagnosis system.

Your role: from the incident, the confirmed root cause and similar
precedents, propose a prioritized remediation plan. This plan is only
PROPOSED for display to a human: no action is automatically executed on a
real system.

Produce a JSON object with three lists of concrete, actionable items:
- "immediat": actions to perform with absolute priority to stop the incident
  (e.g. rollback, restoring a configuration);
- "court_terme": improvements to make in the following days to avoid an
  immediate recurrence (e.g. alerts, timeouts);
- "long_terme": structural/process changes to prevent similar incidents
  (e.g. review gates, load tests).

Draw on the resolutions of similar precedents when relevant. Respond ONLY
with a valid JSON object conforming to the provided schema, with no
surrounding text or Markdown tags."""


def build_prompt(incident: Incident, root_cause: RootCauseHypothesis, kb_matches: KBMatches) -> str:
    return (
        "Structured incident:\n"
        f"{incident.model_dump_json(indent=2)}\n\n"
        "Confirmed root cause:\n"
        f"{root_cause.model_dump_json(indent=2)}\n\n"
        "Similar precedents:\n"
        f"{kb_matches.model_dump_json(indent=2)}"
    )


class RemediationAgent(StructuredAgent[RemediationPlan]):
    """Mitigation + fix plan, behind HITL (agent 5/6)."""

    name = "Remediation"
    instructions = INSTRUCTIONS
    response_model = RemediationPlan
