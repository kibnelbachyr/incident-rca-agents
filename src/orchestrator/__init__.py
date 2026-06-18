# Copyright (c) Microsoft. All rights reserved.

"""Orchestration graph (`WorkflowBuilder`) for incident diagnosis.

Builds the topology described in SPEC.md section 5: agent sequence,
bounded reflection loop (RootCause <-> GatherEvidence), and human
validation gate (HITL) before Remediation.
"""

from __future__ import annotations

from src.orchestrator.graph import build_workflow

__all__ = ["build_workflow"]
