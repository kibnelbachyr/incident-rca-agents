# Copyright (c) Microsoft. All rights reserved.

"""Test isole de l'agent IncidentExtractor (2/6).

Couvre le critere d'acceptation 1 (SPEC.md section 8) : un incident SEV-1
ciblant payment-api / db-pool.
"""

from __future__ import annotations

from src.agents.clients import StubChatClient
from src.agents.incident_extractor import IncidentExtractorAgent, build_prompt
from src.models import Incident, LogAnalysis


async def test_incident_extractor_produces_sev1_on_payment_api(
    stub_client: StubChatClient, sample_log_analysis: LogAnalysis
) -> None:
    agent = IncidentExtractorAgent(stub_client)

    result = await agent.run(build_prompt(sample_log_analysis))

    assert isinstance(result, Incident)
    assert result.severite == "SEV-1"
    assert "payment-api" in result.services
    assert "db-pool" in result.services
    assert result.symptomes
