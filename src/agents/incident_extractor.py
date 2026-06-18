# Copyright (c) Microsoft. All rights reserved.

"""IncidentExtractor agent (SPEC.md section 4.2).

Produces the structured incident object from the log analysis.
Suggested model: light.
"""

from __future__ import annotations

from src.agents.base import StructuredAgent
from src.models import Incident, LogAnalysis

INSTRUCTIONS = """You are the IncidentExtractor agent of a payment incident diagnosis system.

Your role: turn the log analysis (timeline, anomalies, correlated events)
produced by the LogAnalyzer agent into a structured incident object usable by
the next agents. You never communicate directly with other agents.

Produce a JSON object with:
- "titre": short, descriptive title of the incident;
- "severite": severity level in the format "SEV-1" to "SEV-5" (SEV-1 =
  critical production impact, e.g. massive payment transaction failures);
- "services": list of impacted services/components (short technical names,
  e.g. "payment-api", "db-pool");
- "fenetre": time window of the incident, e.g. "14:23 -> ongoing" or
  "14:23 -> 14:41 (resolved)";
- "symptomes": list of symptoms observed by users/operators.

Respond ONLY with a valid JSON object conforming to the provided schema,
with no surrounding text or Markdown tags."""


def build_prompt(log_analysis: LogAnalysis) -> str:
    return "Log analysis produced by the LogAnalyzer agent:\n" f"{log_analysis.model_dump_json(indent=2)}"


class IncidentExtractorAgent(StructuredAgent[Incident]):
    """Produces the structured incident object (agent 2/6)."""

    name = "IncidentExtractor"
    instructions = INSTRUCTIONS
    response_model = Incident
