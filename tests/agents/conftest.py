# Copyright (c) Microsoft. All rights reserved.

"""Fixtures partagees pour les tests isoles de chaque agent.

Donnees figees, coherentes avec `data/payment-incident.log` et
`data/knowledge_base.json`, representant un contexte partage "type" a un
stade avance du diagnostic (apres LogAnalyzer/IncidentExtractor/KBSearch).
"""

from __future__ import annotations

import pytest

from src.agents.clients import StubChatClient
from src.models import Incident, KBMatch, KBMatches, LogAnalysis, RootCauseHypothesis, TimelineEvent


@pytest.fixture
def stub_client() -> StubChatClient:
    return StubChatClient()


@pytest.fixture
def sample_log_analysis() -> LogAnalysis:
    return LogAnalysis(
        timeline=[
            TimelineEvent(time="14:00:11", event="deploy payment-api v2.4.1"),
            TimelineEvent(time="14:00:12", event="config db.max_pool_size=20 (was 40)"),
            TimelineEvent(time="14:22:47", event="pool usage 100% (20/20)"),
            TimelineEvent(time="14:23:15", event="connection acquisition timeout"),
        ],
        anomalies=[
            "pool de connexions sature a 14:22 (20/20)",
            "taux d'erreur passe de 0.18% a 38%",
        ],
        correlated_events=[
            "deploiement v2.4.1 ~22 min avant la saturation du pool",
        ],
    )


@pytest.fixture
def sample_incident() -> Incident:
    return Incident(
        titre="Pic d'echecs de paiement",
        severite="SEV-1",
        services=["payment-api", "db-pool"],
        fenetre="14:23 -> en cours",
        symptomes=[
            "echec de persistance des transactions",
            "pool de connexions sature",
            "retry storm",
        ],
    )


@pytest.fixture
def sample_kb_matches() -> KBMatches:
    return KBMatches(
        matches=[
            KBMatch(id="INC-204", similarite=0.82, resolution="rollback + pool a 40"),
            KBMatch(id="INC-187", similarite=0.61, resolution="circuit breaker Stripe"),
        ]
    )


@pytest.fixture
def sample_root_cause_confirmed() -> RootCauseHypothesis:
    return RootCauseHypothesis(
        cause="Le deploiement v2.4.1 a reduit max_pool_size de 40 a 20",
        raisonnement="La saturation suit le deploiement ; latence Stripe dans la normale",
        confiance=0.88,
        preuves_manquantes=[],
    )
