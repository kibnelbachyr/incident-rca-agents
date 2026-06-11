# Copyright (c) Microsoft. All rights reserved.

"""Agent KBSearch (SPEC.md section 4.3).

Interroge la base de connaissances (RAG, src/tools/knowledge_base.py) pour
trouver des precedents similaires, puis fait confirmer/formater la liste
finale par le client de chat structure. Modele suggere : leger.
"""

from __future__ import annotations

import json

from src.agents.base import StructuredAgent
from src.agents.clients import StructuredChatClient
from src.models import Incident, KBMatches
from src.tools.knowledge_base import KnowledgeBase

INSTRUCTIONS = """Tu es l'agent KBSearch d'un systeme de diagnostic d'incidents de paiement.

Ton role : a partir de l'incident structure et d'une liste de precedents
candidats remontes par une recherche lexicale dans la base de connaissances
(avec un score de similarite brut), produire la liste finale des precedents
pertinents pour les agents suivants.

Pour chaque precedent retenu (au plus ceux fournis en candidats), indique :
- "id": l'identifiant du precedent (ex. "INC-204") ;
- "similarite": un score entre 0 et 1 reflechissant la pertinence vis-a-vis de
  l'incident courant ;
- "resolution": un resume court de la resolution appliquee pour ce precedent.

Conserve tous les candidats fournis, classes du plus au moins pertinent.
Reponds UNIQUEMENT avec un objet JSON valide conforme au schema fourni, sans
texte ni balises Markdown autour."""


def build_prompt(incident: Incident, candidates: KBMatches) -> str:
    return (
        "Incident structure :\n"
        f"{incident.model_dump_json(indent=2)}\n\n"
        "Precedents candidats remontes par la recherche locale (a confirmer/formater) :\n"
        f"{json.dumps(candidates.model_dump()['matches'], indent=2, ensure_ascii=False)}"
    )


class KBSearchAgent(StructuredAgent[KBMatches]):
    """Interroge la base de connaissances et renvoie les precedents (agent 3/6)."""

    name = "KBSearch"
    instructions = INSTRUCTIONS
    response_model = KBMatches

    def __init__(self, client: StructuredChatClient, knowledge_base: KnowledgeBase) -> None:
        super().__init__(client)
        self._knowledge_base = knowledge_base

    async def run(self, incident: Incident) -> KBMatches:  # type: ignore[override]
        candidates = KBMatches(matches=await self._knowledge_base.search(incident, top_k=2))
        prompt = build_prompt(incident, candidates)
        return await super().run(prompt)
