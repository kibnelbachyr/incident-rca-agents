# Copyright (c) Microsoft. All rights reserved.

"""Formatting of Server-Sent Events (SSE) emitted by `src/api/runs.py`."""

from __future__ import annotations

import json
from typing import Any


def sse_event(event: str, data: Any) -> str:
    """Format an SSE message `event: <event>\\ndata: <json>\\n\\n`.

    `data` is serialized as JSON on a single line: an SSE `data:` message
    cannot contain a raw line break.
    """

    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
