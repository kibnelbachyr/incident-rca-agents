# Copyright (c) Microsoft. All rights reserved.

"""API FastAPI exposant le workflow d'orchestration (SPEC.md section 5) sur HTTP.

Voir `src/api/app.py` pour la fabrique d'application et `src/api/runs.py`
pour le contrat des evenements SSE consommes par `frontend/`.
"""

from __future__ import annotations
