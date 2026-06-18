# Copyright (c) Microsoft. All rights reserved.

"""Registers the six agents as "External Agents" in the Microsoft
Foundry project (CLAUDE.md: make the agents visible in the Foundry UI).

The agents in this demo run outside of Foundry (direct Azure OpenAI via
`src/agents/clients.py`): none of them is hosted by the Foundry agent
runtime. `ExternalAgentDefinition` (azure-ai-projects, preview feature)
is designed precisely for this case — the registration is purely declarative
(metadata) and links the OTel spans already emitted by each agent
(`gen_ai.agent.id`, cf. the `id=agent_name` of
`AzureOpenAIStructuredChatClient.get_structured_response`) to an entry visible
in the Foundry project (Agents + Observability > Traces). No agent call is
ever routed through Foundry: runtime behavior is unchanged.

Prerequisites:
- `pip install -e ".[foundry]"` (optional group `azure-ai-projects`,
  absent from the base dependencies: see pyproject.toml).
- `AZURE_FOUNDRY_PROJECT_ENDPOINT` in `.env` (output of `azd` after `azd up`,
  see `infra/resources.bicep` and docs/deployment.md section 8.7/8.13).
- `az login` (mode `AZURE_AUTH_MODE=cli`, the local default) or a managed
  identity (`AZURE_AUTH_MODE=managed_identity`) with a sufficient role on the
  Foundry project to create agent versions.

Usage::

    python -m scripts.register_foundry_agents

Re-run after any change to an agent's name or description — a call with the
same `agent_name` simply creates a new version (version history is kept by
Foundry, no deletion is necessary).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.agents import (
    IncidentExtractorAgent,
    KBSearchAgent,
    LogAnalyzerAgent,
    RemediationAgent,
    RootCauseAgent,
    SummaryAgent,
)
from src.config import get_settings

if TYPE_CHECKING:
    from azure.ai.projects import AIProjectClient


@dataclass(frozen=True)
class AgentRegistration:
    """An agent to register: `name` must match exactly the
    `gen_ai.agent.id` emitted at runtime (otherwise traces don't link
    back to the registration, cf. module docstring)."""

    name: str
    description: str


# Each agent's name is read directly from its class (`StructuredAgent.name`,
# src/agents/base.py) rather than copied as a literal string: this way a
# future agent rename cannot silently drift from `src/agents/clients.py`
# (same `agent_name` on the registration side and on the `id=agent_name`
# side at runtime). The descriptions, on the other hand, are specific to
# this registration (Foundry metadata) and have no runtime equivalent to
# stay in sync with.
_AGENT_DESCRIPTIONS: list[tuple[type, str]] = [
    (
        LogAnalyzerAgent,
        "Normalizes raw incident logs into a timeline, anomalies, and correlated "
        "events. Light model (gpt-4o-mini).",
    ),
    (
        IncidentExtractorAgent,
        "Extracts the structured Incident record (title, severity, services, "
        "symptoms) from the log analysis. Light model.",
    ),
    (
        KBSearchAgent,
        "Searches the knowledge base for similar past incidents (RAG). Light model.",
    ),
    (
        RootCauseAgent,
        "Formulates the root-cause hypothesis with a confidence score and "
        "missing-evidence list that drive the orchestrator's bounded reflection "
        "loop. Strong model (gpt-4o).",
    ),
    (
        RemediationAgent,
        "Proposes a prioritized remediation plan, invoked only after the "
        "human-in-the-loop approval gate; never executes actions on a live "
        "system. Strong model.",
    ),
    (
        SummaryAgent,
        "Writes the final incident report from the accumulated shared context. "
        "Light model.",
    ),
]


def agents_to_register() -> list[AgentRegistration]:
    """Builds the list of agents to register. Pure, no network call."""

    return [
        AgentRegistration(name=agent_cls.name, description=description)
        for agent_cls, description in _AGENT_DESCRIPTIONS
    ]


def register_all(project_client: "AIProjectClient", registrations: list[AgentRegistration]) -> None:
    """Registers each agent via `create_version` (External Agent definition).

    `otel_agent_id` is not explicitly specified: it then defaults to
    `agent_name` (per the `ExternalAgentDefinition` docs), which is exactly
    the value wanted here.
    """

    from azure.ai.projects.models import ExternalAgentDefinition

    for registration in registrations:
        project_client.agents.create_version(
            agent_name=registration.name,
            description=registration.description,
            definition=ExternalAgentDefinition(),
        )
        print(f"Registered '{registration.name}' as an external agent in Microsoft Foundry.")


def main() -> None:
    settings = get_settings()
    if not settings.azure_foundry_project_endpoint:
        raise SystemExit(
            "AZURE_FOUNDRY_PROJECT_ENDPOINT is not configured (.env). "
            "See docs/deployment.md section 8.13."
        )

    from azure.ai.projects import AIProjectClient
    from azure.identity import AzureCliCredential, DefaultAzureCredential

    credential = (
        AzureCliCredential() if settings.azure_auth_mode == "cli" else DefaultAzureCredential()
    )
    project_client = AIProjectClient(
        endpoint=settings.azure_foundry_project_endpoint,
        credential=credential,
        # External Agents is a preview feature of the Foundry API
        # (DECISIONS.md #29): without this flag, the service rejects the registration.
        allow_preview=True,
    )

    register_all(project_client, agents_to_register())


if __name__ == "__main__":
    main()
