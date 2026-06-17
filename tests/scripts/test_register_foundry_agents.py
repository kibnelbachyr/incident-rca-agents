# Copyright (c) Microsoft. All rights reserved.

"""Test du script d'enregistrement External Agent Foundry
(scripts/register_foundry_agents.py, docs/deployment.md section 8.13).

Couvre :
- `agents_to_register()` (pure, sans appel reseau) renvoie exactement les six
  agents reels, avec le meme `name` que `StructuredAgent.name` — requis pour
  que `gen_ai.agent.id` (emis a l'execution avec `id=agent_name`, voir
  `src/agents/clients.py`) se rattache a l'enregistrement Foundry.
- `register_all()` appelle `create_version` une fois par agent avec les bons
  arguments, contre un `project_client` factice (pas d'identifiants Azure
  necessaires), suivant le style de stub deja utilise par `StubChatClient`
  plutot qu'un framework de mock.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from scripts.register_foundry_agents import agents_to_register, register_all
from src.agents import (
    IncidentExtractorAgent,
    KBSearchAgent,
    LogAnalyzerAgent,
    RemediationAgent,
    RootCauseAgent,
    SummaryAgent,
)


def test_agents_to_register_matches_the_six_real_agents() -> None:
    registrations = agents_to_register()

    names = {registration.name for registration in registrations}
    assert names == {
        LogAnalyzerAgent.name,
        IncidentExtractorAgent.name,
        KBSearchAgent.name,
        RootCauseAgent.name,
        RemediationAgent.name,
        SummaryAgent.name,
    }


def test_agents_to_register_have_non_empty_descriptions() -> None:
    registrations = agents_to_register()

    assert len(registrations) == 6
    for registration in registrations:
        assert registration.description


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


def test_register_all_calls_create_version_for_every_agent() -> None:
    pytest.importorskip("azure.ai.projects")  # groupe optionnel [foundry], cf. pyproject.toml

    project_client = _FakeProjectClient()
    registrations = agents_to_register()

    register_all(project_client, registrations)  # type: ignore[arg-type]

    assert len(project_client.agents.calls) == 6
    called_names = {call.agent_name for call in project_client.agents.calls}
    assert called_names == {registration.name for registration in registrations}
    for call in project_client.agents.calls:
        assert call.description
