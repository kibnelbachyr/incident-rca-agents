# Copyright (c) Microsoft. All rights reserved.

"""Cablage OpenTelemetry du Microsoft Agent Framework vers Application Insights /
Microsoft Foundry (CLAUDE.md "Stack technique" - Observabilite).

`configure_observability(settings)` est appelee au demarrage de `src.main` et
`src.api.app`. Si `APPLICATIONINSIGHTS_CONNECTION_STRING` n'est pas configuree
(mode hors-ligne / StubChatClient), c'est un no-op : aucune dependance reseau
n'est ajoutee a la demo locale.

Une fois configuree, l'execution du `Workflow` (`src.orchestrator.build_workflow`)
emet des spans OTel (`workflow.run`, `executor.process <id>`, ...) couvrant les
six agents, la boucle de reflexion RootCause <-> GatherEvidence et la porte HITL
HumanApproval. Ces traces apparaissent dans Application Insights et, si le
projet Microsoft Foundry est connecte a cette meme ressource, dans
Observability > Traces du projet (ai.azure.com) - voir docs/deployment.md #8.12.
"""

from __future__ import annotations

from src.config import Settings


def configure_observability(settings: Settings) -> None:
    """Active l'instrumentation OTel de l'Agent Framework vers Azure Monitor."""

    if not settings.applicationinsights_connection_string:
        return

    from agent_framework.observability import enable_instrumentation
    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor(connection_string=settings.applicationinsights_connection_string)
    enable_instrumentation(enable_sensitive_data=settings.enable_sensitive_data)
