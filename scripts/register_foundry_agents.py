# Copyright (c) Microsoft. All rights reserved.

"""Enregistre les six agents comme « External Agents » dans le projet Microsoft
Foundry (CLAUDE.md : rendre les agents visibles dans l'interface Foundry).

Les agents de cette demo tournent hors de Foundry (Azure OpenAI direct via
`src/agents/clients.py`) : aucun n'est hebergee par le runtime d'agents de
Foundry. `ExternalAgentDefinition` (azure-ai-projects, fonctionnalite preview)
est concue precisement pour ce cas — l'enregistrement est purement declaratif
(metadonnee) et rattache les spans OTel deja emis par chaque agent
(`gen_ai.agent.id`, cf. le `id=agent_name` de
`AzureOpenAIStructuredChatClient.get_structured_response`) a une entree visible
dans le projet Foundry (Agents + Observability > Traces). Aucun appel de
l'agent n'est jamais route via Foundry : le comportement a l'execution est
inchange.

Prerequis :
- `pip install -e ".[foundry]"` (groupe optionnel `azure-ai-projects`,
  absent des dependances de base : voir pyproject.toml).
- `AZURE_FOUNDRY_PROJECT_ENDPOINT` dans `.env` (sortie `azd` apres `azd up`,
  voir `infra/resources.bicep` et docs/deployment.md section 8.7/8.13).
- `az login` (mode `AZURE_AUTH_MODE=cli`, par defaut en local) ou une identite
  managee (`AZURE_AUTH_MODE=managed_identity`) avec un role suffisant sur le
  projet Foundry pour creer des versions d'agent.

Usage::

    python -m scripts.register_foundry_agents

A relancer apres tout changement de nom ou de description d'agent — un appel
avec le meme `agent_name` cree simplement une nouvelle version (l'historique
des versions est conserve par Foundry, aucune suppression n'est necessaire).
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
    """Un agent a enregistrer : `name` doit correspondre exactement au
    `gen_ai.agent.id` emis a l'execution (sinon les traces ne se rattachent
    pas a l'enregistrement, cf. module docstring)."""

    name: str
    description: str


# Le nom de chaque agent est lu directement sur sa classe (`StructuredAgent.name`,
# src/agents/base.py) plutot que recopie en chaine litterale : ainsi un futur
# renommage d'agent ne peut pas faire diverger silencieusement ce script de
# `src/agents/clients.py` (meme `agent_name` cote enregistrement et cote
# `id=agent_name` a l'execution). Les descriptions, elles, sont propres a cet
# enregistrement (metadonnee Foundry) et n'ont pas d'equivalent runtime a
# rester synchronise avec.
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
    """Construit la liste des agents a enregistrer. Pure, sans appel reseau."""

    return [
        AgentRegistration(name=agent_cls.name, description=description)
        for agent_cls, description in _AGENT_DESCRIPTIONS
    ]


def register_all(project_client: "AIProjectClient", registrations: list[AgentRegistration]) -> None:
    """Enregistre chaque agent via `create_version` (definition External Agent).

    `otel_agent_id` n'est pas precise explicitement : il vaut alors par defaut
    `agent_name` (doc `ExternalAgentDefinition`), ce qui est exactement la
    valeur souhaitee ici.
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
            "AZURE_FOUNDRY_PROJECT_ENDPOINT n'est pas configure (.env). "
            "Voir docs/deployment.md section 8.13."
        )

    from azure.ai.projects import AIProjectClient
    from azure.identity import AzureCliCredential, DefaultAzureCredential

    credential = (
        AzureCliCredential() if settings.azure_auth_mode == "cli" else DefaultAzureCredential()
    )
    project_client = AIProjectClient(
        endpoint=settings.azure_foundry_project_endpoint,
        credential=credential,
        # External Agents est une fonctionnalite preview de l'API Foundry
        # (DECISIONS.md #29) : sans ce flag, le service rejette l'enregistrement.
        allow_preview=True,
    )

    register_all(project_client, agents_to_register())


if __name__ == "__main__":
    main()
