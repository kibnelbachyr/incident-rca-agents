# Copyright (c) Microsoft. All rights reserved.

"""RootCause agent (SPEC.md section 4.4).

Formulates the best root cause hypothesis with a confidence score. This is
the "strong" agent (e.g. GPT-4o): its `confiance` score and its
`preuves_manquantes` list drive the orchestrator's reflection loop (SPEC.md
section 5).
"""

from __future__ import annotations

from src.agents.base import StructuredAgent
from src.models import Incident, KBMatches, LogAnalysis, RootCauseHypothesis

INSTRUCTIONS = """You are the RootCause agent, the most important agent of a payment
incident diagnosis system.

Your role: from the structured incident, the log analysis, similar
precedents and, where applicable, additional evidence collected in a
previous round, formulate the BEST root cause hypothesis. You never
communicate directly with other agents.

Produce a JSON object with:
- "cause": the most likely root cause (a factual sentence); if several
  hypotheses remain plausible, describe all of them in this field;
- "raisonnement": the chain of facts and correlations that justifies your
  conclusion (or your hesitation);
- "confiance": a score between 0 and 1 reflecting your certainty;
- "preuves_manquantes": if "confiance" is low, list the precise factual
  elements (e.g. "deployment configuration diff") that would let you decide
  on the next round; empty list if you are confident.

Be honest about your uncertainty: a low score with precise missing evidence
is better than a hasty conclusion. Respond ONLY with a valid JSON object
conforming to the provided schema, with no surrounding text or Markdown
tags."""


def build_prompt(
    incident: Incident,
    log_analysis: LogAnalysis,
    kb_matches: KBMatches,
    *,
    evidence_log: list[str] | None = None,
) -> str:
    sections = [
        f"Structured incident:\n{incident.model_dump_json(indent=2)}",
        f"Log analysis:\n{log_analysis.model_dump_json(indent=2)}",
        f"Similar precedents:\n{kb_matches.model_dump_json(indent=2)}",
    ]

    if evidence_log:
        bullets = "\n".join(f"- {item}" for item in evidence_log)
        sections.append(f"Additional evidence collected in a previous round:\n{bullets}")

    return "\n\n".join(sections)


class RootCauseAgent(StructuredAgent[RootCauseHypothesis]):
    """Root cause hypothesis + confidence score (agent 4/6)."""

    name = "RootCause"
    instructions = INSTRUCTIONS
    response_model = RootCauseHypothesis
