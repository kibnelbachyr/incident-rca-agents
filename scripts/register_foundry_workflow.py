# Copyright (c) Microsoft. All rights reserved.

"""Enregistre le graphe d'orchestration comme un agent de type « Workflow »
dans le projet Microsoft Foundry (CLAUDE.md : rendre l'orchestration visible
dans l'interface Foundry, en complement des six agents, cf.
scripts/register_foundry_agents.py).

Contrairement aux six agents (`ExternalAgentDefinition`, metadata-only), ce
script enregistre un **second artefact** : `scripts/foundry_workflow.yaml`,
une definition CSDL ecrite a la main qui reproduit la topologie de
`src/orchestrator/graph.py` (sequence, boucle de reflexion bornee, porte
HITL) afin qu'elle soit visible/navigable dans le canevas visuel du projet
Foundry. Ce YAML n'est PAS genere depuis le `WorkflowBuilder` Python (aucun
exportateur n'existe) et ne s'execute PAS reellement : l'orchestration qui
tourne pour de vrai reste 100% `src/orchestrator/graph.py` + `executors.py`.
Voir les commentaires en tete de `foundry_workflow.yaml` et DECISIONS.md #30
pour le detail de cette limite.

Prerequis : identiques a `register_foundry_agents.py` (docs/deployment.md
section 8.13/8.14) :
- `pip install -e ".[foundry]"` (groupe optionnel `azure-ai-projects`).
- `AZURE_FOUNDRY_PROJECT_ENDPOINT` dans `.env`.
- `az login` (mode `AZURE_AUTH_MODE=cli`, par defaut) ou identite managee.
- Lancer `python -m scripts.register_foundry_agents` au moins une fois avant
  (les six agents references par `foundry_workflow.yaml` via
  `InvokeAzureAgent` doivent deja exister dans le projet).

Usage::

    python -m scripts.register_foundry_workflow

A relancer apres toute modification de `foundry_workflow.yaml` — comme pour
les agents, un appel avec le meme `agent_name` cree une nouvelle version
(l'historique est conserve par Foundry).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from src.config import get_settings

if TYPE_CHECKING:
    from azure.ai.projects import AIProjectClient

WORKFLOW_NAME = "IncidentRCAWorkflow"
WORKFLOW_DESCRIPTION = (
    "Visual mirror of the incident root-cause orchestration graph "
    "(LogAnalyzer -> IncidentExtractor -> KBSearch -> RootCause, bounded "
    "reflection loop, human-in-the-loop approval, Remediation -> Summary). "
    "Hand-authored CSDL; does not execute the real orchestration — see "
    "scripts/foundry_workflow.yaml header comment."
)
WORKFLOW_YAML_PATH = Path(__file__).resolve().parent / "foundry_workflow.yaml"


def load_workflow_yaml(path: Path = WORKFLOW_YAML_PATH) -> str:
    """Lit la definition CSDL depuis le fichier YAML. Pure, sans appel reseau."""

    return path.read_text(encoding="utf-8")


def register_workflow(project_client: "AIProjectClient", workflow_yaml: str) -> None:
    """Enregistre le workflow via `create_version` (definition Workflow Agent).

    Fonctionnalite preview (`WorkflowAgents=V1Preview`) : le header
    `Foundry-Features` correspondant est ajoute automatiquement par le SDK
    installe dès que `AIProjectClient(..., allow_preview=True)` est utilise
    (confirme par lecture du source installe,
    `azure/ai/projects/operations/_patch_agents.py`) — aucun header manuel a
    construire ici, contrairement a ce qu'indique la doc REST brute.
    """

    from azure.ai.projects.models import WorkflowAgentDefinition

    project_client.agents.create_version(
        agent_name=WORKFLOW_NAME,
        description=WORKFLOW_DESCRIPTION,
        definition=WorkflowAgentDefinition(workflow=workflow_yaml),
    )
    print(f"Registered '{WORKFLOW_NAME}' as a workflow agent in Microsoft Foundry.")


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
        # Workflow Agents est une fonctionnalite preview de l'API Foundry :
        # sans ce flag, le service rejette l'enregistrement (DECISIONS.md #30).
        allow_preview=True,
    )

    register_workflow(project_client, load_workflow_yaml())


if __name__ == "__main__":
    main()
