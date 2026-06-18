# Copyright (c) Microsoft. All rights reserved.

"""KBSearch agent (SPEC.md section 4.3).

Queries the knowledge base (RAG, src/tools/knowledge_base.py) to find similar
precedents, then has the final list confirmed/formatted by the structured
chat client. Suggested model: light.
"""

from __future__ import annotations

import json

from src.agents.base import StructuredAgent
from src.agents.clients import StructuredChatClient
from src.models import Incident, KBMatches
from src.tools.knowledge_base import KnowledgeBase

INSTRUCTIONS = """You are the KBSearch agent of a payment incident diagnosis system.

Your role: from the structured incident and a list of candidate precedents
surfaced by a lexical search in the knowledge base (with a raw similarity
score), produce the final list of precedents relevant to the next agents.

For each retained precedent (at most those provided as candidates), give:
- "id": the precedent's identifier (e.g. "INC-204");
- "similarite": a score between 0 and 1 reflecting relevance to the current
  incident;
- "resolution": a short summary of the resolution applied for this precedent.

Keep all provided candidates, ranked from most to least relevant.
Respond ONLY with a valid JSON object conforming to the provided schema,
with no surrounding text or Markdown tags."""


def build_prompt(incident: Incident, candidates: KBMatches) -> str:
    return (
        "Structured incident:\n"
        f"{incident.model_dump_json(indent=2)}\n\n"
        "Candidate precedents surfaced by the local search (to confirm/format):\n"
        f"{json.dumps(candidates.model_dump()['matches'], indent=2, ensure_ascii=False)}"
    )


class KBSearchAgent(StructuredAgent[KBMatches]):
    """Queries the knowledge base and returns the precedents (agent 3/6)."""

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
