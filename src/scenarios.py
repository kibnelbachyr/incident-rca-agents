# Copyright (c) Microsoft. All rights reserved.

"""Registre des scenarios de demo exposes par la meme interface (UI/CLI/API).

Un scenario associe un identifiant stable a son fichier de logs source et a
des metadonnees d'affichage (UI). Le contenu agent correspondant (reponses
`StubChatClient` en mode hors-ligne) vit dans `src.agents.clients`, garde
separe d'ici pour eviter tout couplage entre ce registre et le detail des
reponses canon par agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.config import REPO_ROOT

DEFAULT_SCENARIO = "db_pool"


@dataclass(frozen=True)
class ScenarioDef:
    """Definition statique d'un scenario de demo."""

    id: str
    label: str
    description: str
    log_path: Path


SCENARIOS: dict[str, ScenarioDef] = {
    "db_pool": ScenarioDef(
        id="db_pool",
        label="DB pool exhaustion",
        description=(
            "A deploy halves the DB connection pool via a config change; saturation and a "
            "payment failure spike surface within ~22 minutes. A transient Stripe latency blip "
            "is a red herring eliminated by the reflection loop."
        ),
        log_path=REPO_ROOT / "data" / "payment-incident.log",
    ),
    "paypal_integration": ScenarioDef(
        id="paypal_integration",
        label="PayPal webhook regression",
        description=(
            "A payment-api release migrates the PayPal SDK and silently breaks webhook "
            "signature verification. Synchronous payments keep working, so the incident is "
            "only discovered 5 days later via a growing stuck-order backlog."
        ),
        log_path=REPO_ROOT / "data" / "payment-paypal-incident.log",
    ),
}


def get_scenario(scenario_id: str | None) -> ScenarioDef:
    """Resout un identifiant de scenario. `None` -> scenario par defaut.

    Leve `KeyError` si un identifiant non vide est fourni mais inconnu (a
    traduire en 400 par l'appelant HTTP plutot que de basculer silencieusement
    sur un autre scenario).
    """

    if scenario_id is None:
        return SCENARIOS[DEFAULT_SCENARIO]
    try:
        return SCENARIOS[scenario_id]
    except KeyError as exc:
        raise KeyError(f"Scenario inconnu : '{scenario_id}'") from exc
