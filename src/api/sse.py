# Copyright (c) Microsoft. All rights reserved.

"""Formatage des evenements Server-Sent Events (SSE) emis par `src/api/runs.py`."""

from __future__ import annotations

import json
from typing import Any


def sse_event(event: str, data: Any) -> str:
    """Formate un message SSE `event: <event>\\ndata: <json>\\n\\n`.

    `data` est serialise en JSON sur une seule ligne : un message `data:` SSE
    ne peut pas contenir de retour a la ligne brut.
    """

    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
