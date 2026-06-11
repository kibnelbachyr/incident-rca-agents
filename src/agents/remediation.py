# Copyright (c) Microsoft. All rights reserved.

"""Agent Remediation (SPEC.md section 4.5).

Propose un plan de remediation priorise. Invoque uniquement APRES validation
humaine (porte HITL de l'orchestrateur, SPEC.md section 5) ; produit
uniquement un plan affiche, aucune action n'est executee sur un vrai systeme
(CLAUDE.md - contraintes a ne pas contourner).
"""

from __future__ import annotations

from src.agents.base import StructuredAgent
from src.models import Incident, KBMatches, RemediationPlan, RootCauseHypothesis

INSTRUCTIONS = """Tu es l'agent Remediation d'un systeme de diagnostic d'incidents de paiement.

Ton role : a partir de l'incident, de la cause racine confirmee et des
precedents similaires, proposer un plan de remediation priorise. Ce plan est
uniquement PROPOSE pour affichage a un humain : aucune action n'est executee
automatiquement sur un systeme reel.

Produis un objet JSON avec trois listes d'actions concretes et actionnables :
- "immediat": actions a effectuer en priorite absolue pour stopper l'incident
  (ex. rollback, restauration d'une configuration) ;
- "court_terme": ameliorations a apporter dans les jours suivants pour eviter
  une recidive immediate (ex. alertes, timeouts) ;
- "long_terme": changements structurels/process pour prevenir des incidents
  similaires (ex. gates de revue, tests de charge).

Inspire-toi des resolutions des precedents similaires quand elles sont
pertinentes. Reponds UNIQUEMENT avec un objet JSON valide conforme au schema
fourni, sans texte ni balises Markdown autour."""


def build_prompt(incident: Incident, root_cause: RootCauseHypothesis, kb_matches: KBMatches) -> str:
    return (
        "Incident structure :\n"
        f"{incident.model_dump_json(indent=2)}\n\n"
        "Cause racine confirmee :\n"
        f"{root_cause.model_dump_json(indent=2)}\n\n"
        "Precedents similaires :\n"
        f"{kb_matches.model_dump_json(indent=2)}"
    )


class RemediationAgent(StructuredAgent[RemediationPlan]):
    """Plan de mitigation + correctif, derriere HITL (agent 5/6)."""

    name = "Remediation"
    instructions = INSTRUCTIONS
    response_model = RemediationPlan
