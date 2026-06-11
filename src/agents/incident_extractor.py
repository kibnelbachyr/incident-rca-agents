# Copyright (c) Microsoft. All rights reserved.

"""Agent IncidentExtractor (SPEC.md section 4.2).

Produit l'objet incident structure a partir de l'analyse de logs.
Modele suggere : leger.
"""

from __future__ import annotations

from src.agents.base import StructuredAgent
from src.models import Incident, LogAnalysis

INSTRUCTIONS = """Tu es l'agent IncidentExtractor d'un systeme de diagnostic d'incidents de paiement.

Ton role : transformer l'analyse de logs (timeline, anomalies, evenements
correles) produite par l'agent LogAnalyzer en un objet incident structure et
exploitable par les agents suivants. Tu ne communiques jamais directement avec
les autres agents.

Produis un objet JSON avec :
- "titre": titre court et descriptif de l'incident ;
- "severite": niveau de severite au format "SEV-1" a "SEV-5" (SEV-1 = impact
  critique en production, ex. echecs massifs de transactions de paiement) ;
- "services": liste des services/composants impactes (noms techniques courts,
  ex. "payment-api", "db-pool") ;
- "fenetre": fenetre temporelle de l'incident, ex. "14:23 -> en cours" ou
  "14:23 -> 14:41 (resolu)" ;
- "symptomes": liste des symptomes observes par les utilisateurs/operateurs.

Reponds UNIQUEMENT avec un objet JSON valide conforme au schema fourni, sans
texte ni balises Markdown autour."""


def build_prompt(log_analysis: LogAnalysis) -> str:
    return "Analyse de logs produite par l'agent LogAnalyzer :\n" f"{log_analysis.model_dump_json(indent=2)}"


class IncidentExtractorAgent(StructuredAgent[Incident]):
    """Produit l'objet incident structure (agent 2/6)."""

    name = "IncidentExtractor"
    instructions = INSTRUCTIONS
    response_model = Incident
