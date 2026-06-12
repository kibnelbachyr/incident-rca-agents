# Copyright (c) Microsoft. All rights reserved.

"""Dependances FastAPI partagees (`Settings`, base de persistance).

Indirection volontaire (plutot que `get_settings()`/`get_persistence_store()`
appeles directement dans les routes) pour permettre aux tests de surcharger
`app.dependency_overrides` (ex. `LocalPersistenceStore` sur un repertoire
temporaire plutot que `output/runs/`).
"""

from __future__ import annotations

from fastapi import Depends

from src.config import Settings, get_settings
from src.tools.persistence import PersistenceStore, get_persistence_store


def settings_dependency() -> Settings:
    return get_settings()


def persistence_dependency(settings: Settings = Depends(settings_dependency)) -> PersistenceStore:
    return get_persistence_store(settings)
