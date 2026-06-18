# Copyright (c) Microsoft. All rights reserved.

"""Search tool over the knowledge base (RAG) of past incidents.

Two implementations share the `KnowledgeBase` interface:

- `LocalKnowledgeBase`: reads `data/knowledge_base.json` (mode `KB_MODE=local`,
  default for the offline demo).
- `AzureAISearchKnowledgeBase`: queries an Azure AI Search index (mode
  `KB_MODE=azure_search`, Azure deployment - see SPEC.md section 7).

`get_knowledge_base(settings)` picks the implementation based on `settings.kb_mode`.
The `KBSearch` agent (src/agents/kb_search.py) consumes this interface and then
has the results confirmed/formatted by the structured chat client.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from src.config import Settings
from src.models import Incident, KBMatch


class KnowledgeBase(Protocol):
    """Common interface: searches for precedents for a given incident."""

    async def search(self, incident: Incident, *, top_k: int = 2) -> list[KBMatch]: ...


class LocalKnowledgeBase:
    """Lexical similarity search over the local JSON file.

    The similarity score is a Jaccard index between the vocabulary of the
    current incident (services + symptomes) and that of each precedent
    (services + symptomes + tags). `knowledge_base.json` holds four past
    incidents; with `top_k=2`, only the two highest-scoring matches are
    returned.
    """

    def __init__(self, path: Path) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self._incidents: list[dict] = data["incidents"]

    async def search(self, incident: Incident, *, top_k: int = 2) -> list[KBMatch]:
        query_terms = _vocabulary([*incident.services, *incident.symptomes])

        scored: list[tuple[float, dict]] = []
        for record in self._incidents:
            record_terms = _vocabulary([*record["services"], *record["symptomes"], *record["tags"]])
            scored.append((_jaccard(query_terms, record_terms), record))

        scored.sort(key=lambda pair: pair[0], reverse=True)

        return [
            KBMatch(id=record["id"], similarite=round(score, 2), resolution=record["resolution"])
            for score, record in scored[:top_k]
        ]


def _vocabulary(phrases: list[str]) -> set[str]:
    """Splits a list of phrases into a set of normalized keywords."""

    words: set[str] = set()
    for phrase in phrases:
        for word in phrase.lower().replace("-", " ").replace("_", " ").split():
            cleaned = word.strip(".,;:()%")
            if len(cleaned) > 2:
                words.add(cleaned)
    return words


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


class AzureAISearchKnowledgeBase:
    """Search over an Azure AI Search index (deployed mode, `KB_MODE=azure_search`)."""

    def __init__(self, *, endpoint: str, index_name: str, credential: object) -> None:
        from azure.search.documents.aio import SearchClient

        self._client = SearchClient(endpoint=endpoint, index_name=index_name, credential=credential)

    async def search(self, incident: Incident, *, top_k: int = 2) -> list[KBMatch]:
        query = " ".join([incident.titre, *incident.services, *incident.symptomes])

        results = await self._client.search(search_text=query, top=top_k)

        matches: list[KBMatch] = []
        async for result in results:
            matches.append(
                KBMatch(
                    id=result["id"],
                    similarite=round(float(result.get("@search.score", 0.0)), 2),
                    resolution=result.get("resolution", ""),
                )
            )
        return matches


def get_knowledge_base(settings: Settings) -> KnowledgeBase:
    """Picks the knowledge base implementation based on `KB_MODE`."""

    if settings.kb_mode == "local":
        return LocalKnowledgeBase(settings.knowledge_base_path)

    if settings.azure_ai_search_endpoint is None:
        raise ValueError("AZURE_AI_SEARCH_ENDPOINT must be set when KB_MODE=azure_search")

    from azure.identity import AzureCliCredential, DefaultAzureCredential

    credential = AzureCliCredential() if settings.azure_auth_mode == "cli" else DefaultAzureCredential()
    return AzureAISearchKnowledgeBase(
        endpoint=settings.azure_ai_search_endpoint,
        index_name=settings.azure_ai_search_index,
        credential=credential,
    )
