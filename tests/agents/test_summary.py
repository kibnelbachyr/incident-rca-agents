# Copyright (c) Microsoft. All rights reserved.

"""Test isole de l'agent Summary (6/6).

Couvre le format du rapport final attendu (scenario-demo-incident-paiement.md
section 5) : sections CAUSE RACINE / REMEDIATION / PRECEDENT LIE.
"""

from __future__ import annotations

from src.agents.clients import StubChatClient
from src.agents.summary import SummaryAgent, build_prompt
from src.models import Incident, IncidentReport, KBMatches, LogAnalysis, RemediationPlan, RootCauseHypothesis


async def test_summary_produces_final_report(
    stub_client: StubChatClient,
    sample_incident: Incident,
    sample_log_analysis: LogAnalysis,
    sample_root_cause_confirmed: RootCauseHypothesis,
    sample_kb_matches: KBMatches,
) -> None:
    agent = SummaryAgent(stub_client)
    remediation_plan = RemediationPlan(
        immediat=["Rollback v2.4.1"],
        court_terme=["Timeout d'acquisition", "Alerte a 80% du pool"],
        long_terme=["Gate de revue config infra"],
    )

    result = await agent.run(
        build_prompt(
            sample_incident,
            sample_log_analysis,
            sample_root_cause_confirmed,
            remediation_plan,
            sample_kb_matches,
        )
    )

    assert isinstance(result, IncidentReport)
    assert result.confiance == 0.88
    assert "INC-204" in (result.precedent_lie or "")
    assert "CAUSE RACINE" in result.texte
    assert "REMÉDIATION" in result.texte
    assert "PRÉCÉDENT LIÉ" in result.texte
