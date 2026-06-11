# Copyright (c) Microsoft. All rights reserved.

"""Test isole de l'agent Remediation (5/6).

Cet agent n'est invoque (par l'orchestrateur) qu'apres validation humaine ;
le test ne couvre que le contrat de sortie `RemediationPlan`.
"""

from __future__ import annotations

from src.agents.clients import StubChatClient
from src.agents.remediation import RemediationAgent, build_prompt
from src.models import Incident, KBMatches, RemediationPlan, RootCauseHypothesis


async def test_remediation_produces_prioritized_plan(
    stub_client: StubChatClient,
    sample_incident: Incident,
    sample_root_cause_confirmed: RootCauseHypothesis,
    sample_kb_matches: KBMatches,
) -> None:
    agent = RemediationAgent(stub_client)

    result = await agent.run(build_prompt(sample_incident, sample_root_cause_confirmed, sample_kb_matches))

    assert isinstance(result, RemediationPlan)
    assert result.immediat
    assert result.court_terme
    assert result.long_terme
