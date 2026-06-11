# Copyright (c) Microsoft. All rights reserved.

"""Agent RootCause (SPEC.md section 4.4).

Formule la meilleure hypothese de cause racine avec un score de confiance.
C'est l'agent "fort" (ex. GPT-4o) : son score `confiance` et sa liste
`preuves_manquantes` pilotent la boucle de reflexion de l'orchestrateur
(SPEC.md section 5).
"""

from __future__ import annotations

from src.agents.base import StructuredAgent
from src.models import Incident, KBMatches, LogAnalysis, RootCauseHypothesis

INSTRUCTIONS = """Tu es l'agent RootCause, l'agent le plus important d'un systeme de
diagnostic d'incidents de paiement.

Ton role : a partir de l'incident structure, de l'analyse de logs, des
precedents similaires et, le cas echeant, de preuves supplementaires
collectees lors d'un tour precedent, formuler la MEILLEURE hypothese de cause
racine. Tu ne communiques jamais directement avec les autres agents.

Produis un objet JSON avec :
- "cause": la cause racine la plus probable (une phrase factuelle) ; si
  plusieurs hypotheses restent plausibles, decris-les toutes dans ce champ ;
- "raisonnement": l'enchainement de faits et de correlations qui justifie ta
  conclusion (ou ton hesitation) ;
- "confiance": un score entre 0 et 1 reflechissant ta certitude ;
- "preuves_manquantes": si "confiance" est faible, liste les elements
  factuels precis (ex. "diff de configuration du deploiement") qui te
  permettraient de trancher au tour suivant ; liste vide si tu es confiant.

Sois honnete sur ton incertitude : il vaut mieux un score bas avec des preuves
manquantes precises qu'une conclusion hative. Reponds UNIQUEMENT avec un objet
JSON valide conforme au schema fourni, sans texte ni balises Markdown autour."""


def build_prompt(
    incident: Incident,
    log_analysis: LogAnalysis,
    kb_matches: KBMatches,
    *,
    evidence_log: list[str] | None = None,
) -> str:
    sections = [
        f"Incident structure :\n{incident.model_dump_json(indent=2)}",
        f"Analyse de logs :\n{log_analysis.model_dump_json(indent=2)}",
        f"Precedents similaires :\n{kb_matches.model_dump_json(indent=2)}",
    ]

    if evidence_log:
        bullets = "\n".join(f"- {item}" for item in evidence_log)
        sections.append(f"Preuves supplementaires collectees lors d'un tour precedent :\n{bullets}")

    return "\n\n".join(sections)


class RootCauseAgent(StructuredAgent[RootCauseHypothesis]):
    """Hypothese de cause racine + score de confiance (agent 4/6)."""

    name = "RootCause"
    instructions = INSTRUCTIONS
    response_model = RootCauseHypothesis
