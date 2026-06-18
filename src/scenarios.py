# Copyright (c) Microsoft. All rights reserved.

"""Registry of demo scenarios exposed through the same interface (UI/CLI/API).

A scenario associates a stable identifier with its source log file and
display metadata (UI). The corresponding agent content (`StubChatClient`
responses in offline mode) lives in `src.agents.clients`, kept separate from
here to avoid any coupling between this registry and the detail of each
agent's canonical responses.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.config import REPO_ROOT

DEFAULT_SCENARIO = "db_pool"


@dataclass(frozen=True)
class ScenarioDef:
    """Static definition of a demo scenario."""

    id: str
    label: str
    description: str
    log_path: Path


SCENARIOS: dict[str, ScenarioDef] = {
    "db_pool": ScenarioDef(
        id="db_pool",
        label="1",
        description=(
            "A deploy halves the DB connection pool via a config change; saturation and a "
            "payment failure spike surface within ~22 minutes. A transient Stripe latency blip "
            "is a red herring eliminated by the reflection loop."
        ),
        log_path=REPO_ROOT / "data" / "payment-incident.log",
    ),
    "paypal_integration": ScenarioDef(
        id="paypal_integration",
        label="2",
        description=(
            "A payment-api release migrates the PayPal SDK and silently breaks webhook "
            "signature verification. Synchronous payments keep working, so the incident is "
            "only discovered 5 days later via a growing stuck-order backlog."
        ),
        log_path=REPO_ROOT / "data" / "payment-paypal-incident.log",
    ),
}


def get_scenario(scenario_id: str | None) -> ScenarioDef:
    """Resolves a scenario identifier. `None` -> default scenario.

    Raises `KeyError` if a non-empty identifier is provided but unknown (to
    be translated into a 400 by the HTTP caller rather than silently falling
    back to another scenario).
    """

    if scenario_id is None:
        return SCENARIOS[DEFAULT_SCENARIO]
    try:
        return SCENARIOS[scenario_id]
    except KeyError as exc:
        raise KeyError(f"Unknown scenario: '{scenario_id}'") from exc
