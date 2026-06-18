# Copyright (c) Microsoft. All rights reserved.

"""Shared FastAPI dependencies (`Settings`, persistence store).

Deliberate indirection (rather than calling `get_settings()`/
`get_persistence_store()` directly in the routes) to let tests override
`app.dependency_overrides` (e.g. `LocalPersistenceStore` on a temporary
directory instead of `output/runs/`).
"""

from __future__ import annotations

from fastapi import Depends

from src.config import Settings, get_settings
from src.tools.persistence import PersistenceStore, get_persistence_store


def settings_dependency() -> Settings:
    return get_settings()


def persistence_dependency(settings: Settings = Depends(settings_dependency)) -> PersistenceStore:
    return get_persistence_store(settings)
