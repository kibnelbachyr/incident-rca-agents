# Copyright (c) Microsoft. All rights reserved.

"""FastAPI API exposing the orchestration workflow (SPEC.md section 5) over HTTP.

See `src/api/app.py` for the application factory and `src/api/runs.py`
for the contract of SSE events consumed by `frontend/`.
"""

from __future__ import annotations
