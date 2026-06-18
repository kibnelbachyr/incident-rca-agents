# Copyright (c) Microsoft. All rights reserved.

"""OpenTelemetry wiring from the Microsoft Agent Framework to Application Insights /
Microsoft Foundry (CLAUDE.md "Technical stack" - Observability).

`configure_observability(settings)` is called at startup by `src.main` and
`src.api.app`. If `APPLICATIONINSIGHTS_CONNECTION_STRING` is not configured
(offline mode / StubChatClient), it is a no-op: no network dependency is
added to the local demo.

Once configured, running the `Workflow` (`src.orchestrator.build_workflow`)
emits OTel spans (`workflow.run`, `executor.process <id>`, ...) covering the
six agents, the RootCause <-> GatherEvidence reflection loop, and the
HumanApproval HITL gate. These traces appear in Application Insights and, if
the Microsoft Foundry project is connected to that same resource, in the
project's Observability > Traces (ai.azure.com) - see docs/deployment.md #8.12.
"""

from __future__ import annotations

from src.config import Settings


def configure_observability(settings: Settings) -> None:
    """Enable Agent Framework OTel instrumentation toward Azure Monitor."""

    if not settings.applicationinsights_connection_string:
        return

    from agent_framework.observability import create_resource, enable_instrumentation
    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor(
        connection_string=settings.applicationinsights_connection_string,
        resource=create_resource(),
        enable_live_metrics=True,
        sampling_ratio=1.0,
    )
    enable_instrumentation(enable_sensitive_data=settings.enable_sensitive_data)
