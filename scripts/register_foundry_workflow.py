# Copyright (c) Microsoft. All rights reserved.

"""Registers the orchestration graph as a "Workflow"-type agent in the
Microsoft Foundry project (CLAUDE.md: make the orchestration visible in
the Foundry UI, in addition to the six agents, cf.
scripts/register_foundry_agents.py).

Unlike the six agents (`ExternalAgentDefinition`, metadata-only), this
script registers a **second artifact**: `scripts/foundry_workflow.yaml`,
a hand-written CSDL definition that reproduces the topology of
`src/orchestrator/graph.py` (sequence, bounded reflection loop, HITL
gate) so that it is visible/navigable in the Foundry project's visual
canvas. This YAML is NOT generated from the Python `WorkflowBuilder` (no
exporter exists) and does NOT actually execute: the orchestration that
really runs remains 100% `src/orchestrator/graph.py` + `executors.py`.
See the header comments in `foundry_workflow.yaml` and DECISIONS.md #30
for details on this limitation.

Prerequisites: identical to `register_foundry_agents.py` (docs/deployment.md
section 8.13/8.14):
- `pip install -e ".[foundry]"` (optional group `azure-ai-projects`).
- `AZURE_FOUNDRY_PROJECT_ENDPOINT` in `.env`.
- `az login` (mode `AZURE_AUTH_MODE=cli`, the default) or a managed identity.
- Run `python -m scripts.register_foundry_agents` at least once beforehand
  (the six agents referenced by `foundry_workflow.yaml` via
  `InvokeAzureAgent` must already exist in the project).

Usage::

    python -m scripts.register_foundry_workflow

Re-run after any change to `foundry_workflow.yaml` — as with the agents, a
call with the same `agent_name` creates a new version (history is kept by
Foundry).
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
    """Reads the CSDL definition from the YAML file. Pure, no network call."""

    return path.read_text(encoding="utf-8")


def register_workflow(project_client: "AIProjectClient", workflow_yaml: str) -> None:
    """Registers the workflow via `create_version` (Workflow Agent definition).

    Preview feature (`WorkflowAgents=V1Preview`): the corresponding
    `Foundry-Features` header is added automatically by the installed SDK
    as soon as `AIProjectClient(..., allow_preview=True)` is used
    (confirmed by reading the installed source,
    `azure/ai/projects/operations/_patch_agents.py`) — no manual header to
    build here, contrary to what the raw REST docs suggest.
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
        # Workflow Agents is a preview feature of the Foundry API:
        # without this flag, the service rejects the registration (DECISIONS.md #30).
        allow_preview=True,
    )

    register_workflow(project_client, load_workflow_yaml())


if __name__ == "__main__":
    main()
