# Copyright (c) Microsoft. All rights reserved.

"""Agent Summary (SPEC.md section 4.6).

Redige le rapport d'incident final (texte pret-a-coller + champs cles), a
partir de l'ensemble du contexte accumule par l'orchestrateur. Modele
suggere : leger.
"""

from __future__ import annotations

from src.agents.base import StructuredAgent
from src.models import Incident, IncidentReport, KBMatches, LogAnalysis, RemediationPlan, RootCauseHypothesis

INSTRUCTIONS = """Tu es l'agent Summary d'un systeme de diagnostic d'incidents de paiement.

Ton role : rediger le rapport final de l'incident, a partir de l'incident
structure, de l'analyse de logs, de la cause racine confirmee, du plan de
remediation approuve et des precedents similaires.

Produis un objet JSON avec :
- "titre": titre du rapport, ex. "INCIDENT SEV-1 - Pic d'echecs de paiement" ;
- "fenetre": fenetre temporelle de l'incident (mentionne "resolu" si applicable) ;
- "impact": description courte de l'impact (ex. "38% des transactions en echec") ;
- "cause_racine": description en prose de la cause racine confirmee ;
- "confiance": le score de confiance de la cause racine (0-1) ;
- "remediation": liste ordonnee et priorisee des actions de remediation
  (fusionne immediat/court terme/long terme en une seule liste numerotable) ;
- "precedent_lie": reference courte au precedent le plus pertinent (ex.
  "INC-204 (meme schema, meme resolution)"), ou null si aucun ne s'applique ;
- "texte": le rapport complet, en texte brut pret a coller dans un
  post-mortem, avec les sections "CAUSE RACINE (confiance X)", "REMEDIATION"
  (liste numerotee) et "PRECEDENT LIE".

Reponds UNIQUEMENT avec un objet JSON valide conforme au schema fourni, sans
texte ni balises Markdown autour."""


def build_prompt(
    incident: Incident,
    log_analysis: LogAnalysis,
    root_cause: RootCauseHypothesis,
    remediation_plan: RemediationPlan,
    kb_matches: KBMatches,
) -> str:
    return (
        "Incident structure :\n"
        f"{incident.model_dump_json(indent=2)}\n\n"
        "Analyse de logs :\n"
        f"{log_analysis.model_dump_json(indent=2)}\n\n"
        "Cause racine confirmee :\n"
        f"{root_cause.model_dump_json(indent=2)}\n\n"
        "Plan de remediation approuve :\n"
        f"{remediation_plan.model_dump_json(indent=2)}\n\n"
        "Precedents similaires :\n"
        f"{kb_matches.model_dump_json(indent=2)}"
    )


class SummaryAgent(StructuredAgent[IncidentReport]):
    """Redige le rapport d'incident final (agent 6/6)."""

    name = "Summary"
    instructions = INSTRUCTIONS
    response_model = IncidentReport
