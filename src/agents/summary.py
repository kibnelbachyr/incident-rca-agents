# Copyright (c) Microsoft. All rights reserved.

"""Summary agent (SPEC.md section 4.6).

Writes the final incident report (ready-to-paste text + key fields), from
the full context accumulated by the orchestrator. Suggested model: light.
"""

from __future__ import annotations

from src.agents.base import StructuredAgent
from src.models import Incident, IncidentReport, KBMatches, LogAnalysis, RemediationPlan, RootCauseHypothesis

INSTRUCTIONS = """You are the Summary agent of a payment incident diagnosis system.

Your role: write the incident's final report, from the structured incident,
the log analysis, the confirmed root cause, the approved remediation plan and
similar precedents.

Produce a JSON object with:
- "titre": report title, e.g. "INCIDENT SEV-1 - Payment failure spike";
- "fenetre": time window of the incident (mention "resolved" if applicable);
- "impact": short description of the impact (e.g. "38% of transactions
  failing");
- "cause_racine": prose description of the confirmed root cause;
- "confiance": the root cause's confidence score (0-1);
- "remediation": ordered, prioritized list of remediation actions (merges
  immediate/short-term/long-term into a single numberable list);
- "precedent_lie": short reference to the most relevant precedent (e.g.
  "INC-204 (same pattern, same resolution)"), or null if none applies;
- "texte": the full report, as plain text ready to paste into a post-mortem,
  with the sections "ROOT CAUSE (confidence X)", "REMEDIATION" (numbered
  list) and "RELATED PRECEDENT".

Respond ONLY with a valid JSON object conforming to the provided schema,
with no surrounding text or Markdown tags."""


def build_prompt(
    incident: Incident,
    log_analysis: LogAnalysis,
    root_cause: RootCauseHypothesis,
    remediation_plan: RemediationPlan,
    kb_matches: KBMatches,
) -> str:
    return (
        "Structured incident:\n"
        f"{incident.model_dump_json(indent=2)}\n\n"
        "Log analysis:\n"
        f"{log_analysis.model_dump_json(indent=2)}\n\n"
        "Confirmed root cause:\n"
        f"{root_cause.model_dump_json(indent=2)}\n\n"
        "Approved remediation plan:\n"
        f"{remediation_plan.model_dump_json(indent=2)}\n\n"
        "Similar precedents:\n"
        f"{kb_matches.model_dump_json(indent=2)}"
    )


class SummaryAgent(StructuredAgent[IncidentReport]):
    """Writes the final incident report (agent 6/6)."""

    name = "Summary"
    instructions = INSTRUCTIONS
    response_model = IncidentReport
