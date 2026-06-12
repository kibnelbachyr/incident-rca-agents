# Copyright (c) Microsoft. All rights reserved.

"""Persistance des executions terminees (SPEC.md section 7, Cosmos DB optionnel).

Deux implementations partagent l'interface `PersistenceStore` :

- `LocalPersistenceStore` : un fichier JSON par execution dans `output/runs/`
  (mode hors-ligne, par defaut pour la demo - DECISIONS.md #3).
- `CosmosPersistenceStore` : un document par execution dans un conteneur
  Azure Cosmos DB (mode deploye, `COSMOS_ENDPOINT` defini).

`get_persistence_store(settings)` choisit l'implementation selon
`settings.cosmos_endpoint`. L'API (`src/api/runs.py`) appelle `save()` une
fois l'execution terminee (approuvee ou refusee) ; `list_records`/
`get_record` alimentent l'historique consulte depuis l'UI.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from src.config import REPO_ROOT, Settings
from src.models import SharedContext


class IncidentRecord(BaseModel):
    """Une execution terminee, telle que persistee pour l'historique de l'UI."""

    id: str
    started_at: datetime
    finished_at: datetime
    approved: bool | None
    context: SharedContext


class IncidentRecordSummary(BaseModel):
    """Vue resumee d'un `IncidentRecord`, utilisee par la liste d'historique."""

    id: str
    started_at: datetime
    finished_at: datetime
    approved: bool | None
    titre: str | None
    severite: str | None
    cause: str | None
    confiance: float | None


def _summarize(record: IncidentRecord) -> IncidentRecordSummary:
    incident = record.context.incident
    root_cause = record.context.root_cause
    return IncidentRecordSummary(
        id=record.id,
        started_at=record.started_at,
        finished_at=record.finished_at,
        approved=record.approved,
        titre=incident.titre if incident else None,
        severite=incident.severite if incident else None,
        cause=root_cause.cause if root_cause else None,
        confiance=root_cause.confiance if root_cause else None,
    )


class PersistenceStore(Protocol):
    """Interface commune : sauvegarde et relecture des executions terminees."""

    async def save(self, record: IncidentRecord) -> None: ...

    async def list_records(self, *, limit: int = 20) -> list[IncidentRecordSummary]: ...

    async def get_record(self, run_id: str) -> IncidentRecord | None: ...


class LocalPersistenceStore:
    """Un fichier JSON par execution dans `path` (mode hors-ligne, KB_MODE=local)."""

    def __init__(self, path: Path) -> None:
        self._path = path

    async def save(self, record: IncidentRecord) -> None:
        self._path.mkdir(parents=True, exist_ok=True)
        (self._path / f"{record.id}.json").write_text(record.model_dump_json(indent=2), encoding="utf-8")

    async def list_records(self, *, limit: int = 20) -> list[IncidentRecordSummary]:
        if not self._path.is_dir():
            return []
        files = sorted(self._path.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        records = [IncidentRecord.model_validate_json(f.read_text(encoding="utf-8")) for f in files[:limit]]
        return [_summarize(record) for record in records]

    async def get_record(self, run_id: str) -> IncidentRecord | None:
        file = self._path / f"{run_id}.json"
        if not file.is_file():
            return None
        return IncidentRecord.model_validate_json(file.read_text(encoding="utf-8"))


class CosmosPersistenceStore:
    """Conteneur Azure Cosmos DB (mode deploye, `COSMOS_ENDPOINT` defini).

    Le compte, la base et le conteneur (partition key `/id`) sont
    provisionnes par `infra/` (Bicep) ; cette classe ne fait que lire/ecrire
    des documents via le plan de donnees (role `Cosmos DB Built-in Data
    Contributor`, voir SPEC.md section 7).
    """

    def __init__(self, *, endpoint: str, database: str, container: str, credential: object) -> None:
        from azure.cosmos.aio import CosmosClient

        self._client = CosmosClient(endpoint, credential=credential)
        self._database = database
        self._container = container

    def _container_client(self):  # noqa: ANN202 - type vit dans azure.cosmos.aio
        return self._client.get_database_client(self._database).get_container_client(self._container)

    async def save(self, record: IncidentRecord) -> None:
        await self._container_client().upsert_item(record.model_dump(mode="json"))

    async def list_records(self, *, limit: int = 20) -> list[IncidentRecordSummary]:
        container = self._container_client()
        records = [
            IncidentRecord.model_validate(item)
            async for item in container.query_items(query="SELECT * FROM c", enable_cross_partition_query=True)
        ]
        records.sort(key=lambda record: record.started_at, reverse=True)
        return [_summarize(record) for record in records[:limit]]

    async def get_record(self, run_id: str) -> IncidentRecord | None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            item = await self._container_client().read_item(item=run_id, partition_key=run_id)
        except CosmosResourceNotFoundError:
            return None
        return IncidentRecord.model_validate(item)


def get_persistence_store(settings: Settings) -> PersistenceStore:
    """Choisit l'implementation de persistance selon `COSMOS_ENDPOINT`."""

    if settings.cosmos_endpoint is None:
        return LocalPersistenceStore(REPO_ROOT / "output" / "runs")

    from azure.identity.aio import AzureCliCredential, DefaultAzureCredential

    credential = AzureCliCredential() if settings.azure_auth_mode == "cli" else DefaultAzureCredential()
    return CosmosPersistenceStore(
        endpoint=settings.cosmos_endpoint,
        database=settings.cosmos_database,
        container=settings.cosmos_container,
        credential=credential,
    )
