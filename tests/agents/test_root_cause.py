# Copyright (c) Microsoft. All rights reserved.

"""Test isole de l'agent RootCause (4/6).

Couvre les criteres d'acceptation 3 et 4 (SPEC.md section 8) : le 1er passage
est sous le seuil de confiance avec des preuves manquantes ; le 2e passage
(apres GatherEvidence) est au-dessus du seuil et designe `max_pool_size`.
"""

from __future__ import annotations

from src.agents.clients import StubChatClient
from src.agents.root_cause import RootCauseAgent, build_prompt
from src.models import Incident, KBMatches, LogAnalysis, RootCauseHypothesis


async def test_root_cause_first_pass_is_below_threshold(
    stub_client: StubChatClient,
    sample_incident: Incident,
    sample_log_analysis: LogAnalysis,
    sample_kb_matches: KBMatches,
) -> None:
    agent = RootCauseAgent(stub_client)

    result = await agent.run(build_prompt(sample_incident, sample_log_analysis, sample_kb_matches))

    assert isinstance(result, RootCauseHypothesis)
    assert result.confiance < 0.75
    assert result.preuves_manquantes


async def test_root_cause_second_pass_designates_max_pool_size(
    stub_client: StubChatClient,
    sample_incident: Incident,
    sample_log_analysis: LogAnalysis,
    sample_kb_matches: KBMatches,
) -> None:
    agent = RootCauseAgent(stub_client)

    await agent.run(build_prompt(sample_incident, sample_log_analysis, sample_kb_matches))  # 1er passage
    second = await agent.run(
        build_prompt(
            sample_incident,
            sample_log_analysis,
            sample_kb_matches,
            evidence_log=["diff de deploiement : db.max_pool_size 40 -> 20"],
        )
    )

    assert second.confiance >= 0.75
    assert "max_pool_size" in second.cause
    assert second.preuves_manquantes == []
