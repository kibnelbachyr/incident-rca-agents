# Copyright (c) Microsoft. All rights reserved.

"""Agent LogAnalyzer (SPEC.md section 4.1).

Normalise des logs bruts en timeline + anomalies + evenements correles.
Modele suggere : leger (ex. gpt-4o-mini).
"""

from __future__ import annotations

from src.agents.base import StructuredAgent
from src.models import LogAnalysis

INSTRUCTIONS = """Tu es l'agent LogAnalyzer d'un systeme de diagnostic d'incidents de paiement.

Ton role : transformer des logs bruts en signal exploitable pour les agents
suivants. Tu ne communiques jamais directement avec les autres agents ; tu
recois un texte de l'orchestrateur et tu lui renvoies un objet JSON.

A partir des logs fournis (et, le cas echeant, des points a investiguer en
priorite), produis :
- "timeline": liste ordonnee des evenements cles, chacun avec "time" (HH:MM:SS)
  et "event" (description courte et factuelle) ;
- "anomalies": liste des anomalies detectees (saturation, pics de latence ou
  d'erreur, comportements inhabituels) ;
- "correlated_events": liste des correlations temporelles entre evenements
  (ex. un changement de configuration suivi peu apres d'une degradation).

Reponds UNIQUEMENT avec un objet JSON valide conforme au schema fourni, sans
texte ni balises Markdown autour."""


def build_prompt(raw_logs: str, *, focus: list[str] | None = None) -> str:
    """Construit le prompt utilisateur a partir des logs bruts.

    `focus` est utilise par l'etape `GatherEvidence` de l'orchestrateur pour
    cibler une nouvelle analyse sur les `preuves_manquantes` identifiees par
    l'agent RootCause (SPEC.md section 5).
    """

    sections = [f"Logs bruts du systeme de paiement :\n{raw_logs}"]

    if focus:
        points = "\n".join(f"- {item}" for item in focus)
        sections.append(
            "L'agent RootCause a besoin des elements suivants pour trancher entre "
            f"plusieurs hypotheses ; concentre ton analyse dessus :\n{points}"
        )

    return "\n\n".join(sections)


class LogAnalyzerAgent(StructuredAgent[LogAnalysis]):
    """Normalise les logs et detecte anomalies + timeline (agent 1/6)."""

    name = "LogAnalyzer"
    instructions = INSTRUCTIONS
    response_model = LogAnalysis
