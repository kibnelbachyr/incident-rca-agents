# Copyright (c) Microsoft. All rights reserved.

"""Base class shared by the six specialized agents.

Each agent declares its `name` (used as the stub key and as the real
`Agent`'s name), its `instructions` (system prompt) and its `response_model`
(output pydantic contract, src/models.py). `run(prompt)` delegates to the
injected `StructuredChatClient` (stub or real) and returns a validated
instance of `response_model`.

Agents are stateless (SPEC.md section 2): they keep nothing between calls
and never reference each other.
"""

from __future__ import annotations

from typing import ClassVar, Generic, TypeVar

from pydantic import BaseModel

from src.agents.clients import StructuredChatClient

ResponseT = TypeVar("ResponseT", bound=BaseModel)


class StructuredAgent(Generic[ResponseT]):
    """Stateless agent that produces a JSON output validated by pydantic."""

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
