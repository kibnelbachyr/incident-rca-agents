# Copyright (c) Microsoft. All rights reserved.

"""Graphe d'orchestration (`WorkflowBuilder`) du diagnostic d'incidents.

Construit la topologie decrite dans SPEC.md section 5 : sequence d'agents,
boucle de reflexion bornee (RootCause <-> GatherEvidence) et porte de
validation humaine (HITL) avant Remediation.
"""

from __future__ import annotations

from src.orchestrator.graph import build_workflow

__all__ = ["build_workflow"]
