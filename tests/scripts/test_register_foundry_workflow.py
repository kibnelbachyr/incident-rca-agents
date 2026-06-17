# Copyright (c) Microsoft. All rights reserved.

"""Test du script d'enregistrement Workflow Agent Foundry
(scripts/register_foundry_workflow.py, docs/deployment.md section 8.14).

Couvre :
- `load_workflow_yaml()` (pure, sans appel reseau) renvoie un CSDL YAML non
  vide, parseable, dont la structure de premier niveau correspond a la
  topologie de `src/orchestrator/graph.py` (sequence, boucle de reflexion,
  porte HITL) - cf. `scripts/foundry_workflow.yaml`.
- `register_workflow()` appelle `create_version` une seule fois avec le bon
  `agent_name`, une description non vide et une `WorkflowAgentDefinition`
  portant le YAML, contre un `project_client` factice (meme convention de
  stub que `tests/scripts/test_register_foundry_agents.py`, pas de framework
  de mock).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
import yaml

from scripts.register_foundry_workflow import (
    WORKFLOW_NAME,
    load_workflow_yaml,
    register_workflow,
)


def test_load_workflow_yaml_is_well_formed_csdl() -> None:
    workflow_yaml = load_workflow_yaml()

    assert workflow_yaml.strip()
    definition = yaml.safe_load(workflow_yaml)

    assert definition["kind"] == "Workflow"
    assert definition["trigger"]["kind"] == "OnConversationStart"

    action_ids = {action["id"] for action in definition["trigger"]["actions"]}
    assert action_ids == {
        "capture_raw_logs",
        "init_loop_state",
        "invoke_log_analyzer",
        "invoke_incident_extractor",
        "invoke_kb_search",
        "invoke_root_cause",
        "check_needs_more_evidence",
        "human_approval_gate",
        "check_approval",
        "end_workflow",
    }


def test_load_workflow_yaml_references_the_six_registered_agents() -> None:
    definition = yaml.safe_load(load_workflow_yaml())

    def iter_actions(actions: list[dict]) -> list[dict]:
        for action in actions:
            yield action
            for branch in ("then", "else"):
                if branch in action:
                    yield from iter_actions(action[branch])

    invoked_agent_names = {
        action["agent"]["name"]
        for action in iter_actions(definition["trigger"]["actions"])
        if action["kind"] == "InvokeAzureAgent"
    }
    assert invoked_agent_names == {
        "LogAnalyzer",
        "IncidentExtractor",
        "KBSearch",
        "RootCause",
        "Remediation",
        "Summary",
    }


@dataclass
class _FakeCreateVersionCall:
    agent_name: str
    description: str
    definition: object


@dataclass
class _FakeAgentsOperations:
    calls: list[_FakeCreateVersionCall] = field(default_factory=list)

    def create_version(self, *, agent_name: str, description: str, definition: object) -> None:
        self.calls.append(
            _FakeCreateVersionCall(agent_name=agent_name, description=description, definition=definition)
        )


@dataclass
class _FakeProjectClient:
    agents: _FakeAgentsOperations = field(default_factory=_FakeAgentsOperations)


def test_register_workflow_calls_create_version_once() -> None:
    pytest.importorskip("azure.ai.projects")  # groupe optionnel [foundry], cf. pyproject.toml
    from azure.ai.projects.models import WorkflowAgentDefinition

    project_client = _FakeProjectClient()
    workflow_yaml = load_workflow_yaml()

    register_workflow(project_client, workflow_yaml)  # type: ignore[arg-type]

    assert len(project_client.agents.calls) == 1
    call = project_client.agents.calls[0]
    assert call.agent_name == WORKFLOW_NAME
    assert call.description
    assert isinstance(call.definition, WorkflowAgentDefinition)
    assert call.definition.workflow == workflow_yaml
