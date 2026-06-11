# Copyright (c) Microsoft. All rights reserved.

"""Test isole de l'agent LogAnalyzer (1/6)."""

from __future__ import annotations

from src.agents.clients import StubChatClient
from src.agents.log_analyzer import LogAnalyzerAgent, build_prompt
from src.models import LogAnalysis


async def test_log_analyzer_produces_timeline_and_anomalies(stub_client: StubChatClient) -> None:
    agent = LogAnalyzerAgent(stub_client)

    result = await agent.run(build_prompt("14:00:11 INFO deploy payment-api v2.4.1"))

    assert isinstance(result, LogAnalysis)
    assert result.timeline
    assert result.anomalies
    assert result.correlated_events
    assert any("v2.4.1" in event.event for event in result.timeline)


async def test_log_analyzer_second_pass_focuses_on_missing_evidence(stub_client: StubChatClient) -> None:
    agent = LogAnalyzerAgent(stub_client)

    first = await agent.run(build_prompt("logs..."))
    second = await agent.run(build_prompt("logs...", focus=["diff de configuration du deploiement v2.4.1"]))

    assert first != second
    assert any("max_pool_size" in event.event for event in second.timeline)
