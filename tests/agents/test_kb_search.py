# Copyright (c) Microsoft. All rights reserved.

"""Test isole de l'agent KBSearch (3/6).

Couvre le critere d'acceptation 2 (SPEC.md section 8) : deux precedents
(INC-204 et INC-187) sont retournes.
"""

from __future__ import annotations

from src.agents.clients import StubChatClient
from src.agents.kb_search import KBSearchAgent
from src.config import get_settings
from src.models import Incident, KBMatches
from src.tools.knowledge_base import LocalKnowledgeBase


async def test_kb_search_returns_two_precedents(stub_client: StubChatClient, sample_incident: Incident) -> None:
    settings = get_settings()
    knowledge_base = LocalKnowledgeBase(settings.knowledge_base_path)
    agent = KBSearchAgent(stub_client, knowledge_base)

    result = await agent.run(sample_incident)

    assert isinstance(result, KBMatches)
    ids = {match.id for match in result.matches}
    assert ids == {"INC-204", "INC-187"}
    assert all(0.0 <= match.similarite <= 1.0 for match in result.matches)


async def test_local_knowledge_base_ranks_pool_incident_first(sample_incident: Incident) -> None:
    settings = get_settings()
    knowledge_base = LocalKnowledgeBase(settings.knowledge_base_path)

    matches = await knowledge_base.search(sample_incident, top_k=2)

    assert len(matches) == 2
    assert matches[0].id == "INC-204"
