# Copyright (c) Microsoft. All rights reserved.

"""LogAnalyzer agent (SPEC.md section 4.1).

Normalizes raw logs into a timeline + anomalies + correlated events.
Suggested model: light (e.g. gpt-4o-mini).
"""

from __future__ import annotations

from src.agents.base import StructuredAgent
from src.models import LogAnalysis

INSTRUCTIONS = """You are the LogAnalyzer agent of a payment incident diagnosis system.

Your role: turn raw logs into actionable signal for the next agents. You
never communicate directly with other agents; you receive text from the
orchestrator and return a JSON object to it.

From the provided logs (and, where applicable, priority points to
investigate), produce:
- "timeline": ordered list of key events, each with "time" (HH:MM:SS)
  and "event" (short, factual description);
- "anomalies": list of detected anomalies (saturation, latency or error
  spikes, unusual behavior);
- "correlated_events": list of temporal correlations between events
  (e.g. a configuration change followed shortly after by a degradation).

Respond ONLY with a valid JSON object conforming to the provided schema,
with no surrounding text or Markdown tags."""


def build_prompt(raw_logs: str, *, focus: list[str] | None = None) -> str:
    """Builds the user prompt from the raw logs.

    `focus` is used by the orchestrator's `GatherEvidence` step to target a
    new analysis on the `preuves_manquantes` identified by the RootCause
    agent (SPEC.md section 5).
    """

    sections = [f"Raw payment system logs:\n{raw_logs}"]

    if focus:
        points = "\n".join(f"- {item}" for item in focus)
        sections.append(
            "The RootCause agent needs the following elements to decide between "
            f"several hypotheses; focus your analysis on them:\n{points}"
        )

    return "\n\n".join(sections)


class LogAnalyzerAgent(StructuredAgent[LogAnalysis]):
    """Normalizes logs and detects anomalies + timeline (agent 1/6)."""

    name = "LogAnalyzer"
    instructions = INSTRUCTIONS
    response_model = LogAnalysis
