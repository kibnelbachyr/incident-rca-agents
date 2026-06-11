# Copyright (c) Microsoft. All rights reserved.

"""Classe de base commune aux six agents specialises.

Chaque agent declare son `name` (utilise comme cle dans le stub et comme nom
de l'`Agent` reel), ses `instructions` (prompt systeme, en francais) et son
`response_model` (contrat pydantic de sortie, src/models.py). `run(prompt)`
delegue au `StructuredChatClient` injecte (stub ou reel) et renvoie une
instance validee de `response_model`.

Les agents sont sans etat (SPEC.md section 2) : ils ne conservent rien entre
deux appels et ne se referencent jamais entre eux.
"""

from __future__ import annotations

from typing import ClassVar, Generic, TypeVar

from pydantic import BaseModel

from src.agents.clients import StructuredChatClient

ResponseT = TypeVar("ResponseT", bound=BaseModel)


class StructuredAgent(Generic[ResponseT]):
    """Agent stateless qui produit une sortie JSON validee par pydantic."""

    name: ClassVar[str]
    instructions: ClassVar[str]
    response_model: ClassVar[type[BaseModel]]

    def __init__(self, client: StructuredChatClient) -> None:
        self._client = client

    async def run(self, prompt: str) -> ResponseT:
        result = await self._client.get_structured_response(
            agent_name=self.name,
            instructions=self.instructions,
            prompt=prompt,
            response_model=self.response_model,
        )
        return result  # type: ignore[return-value]
