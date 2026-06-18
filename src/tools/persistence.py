# Copyright (c) Microsoft. All rights reserved.

"""Persistence of finished runs (SPEC.md section 7, Cosmos DB optional).

Two implementations share the `PersistenceStore` interface:

- `LocalPersistenceStore`: one JSON file per run in `output/runs/`
  (offline mode, default for the demo - DECISIONS.md #3).
- `CosmosPersistenceStore`: one document per run in an Azure Cosmos DB
  container (deployed mode, `COSMOS_ENDPOINT` set).

`get_persistence_store(settings)` picks the implementation based on
`settings.cosmos_endpoint`. The API (`src/api/runs.py`) calls `save()` once
the run is finished (approved or rejected); `list_records`/`get_record`
feed the history viewed from the UI.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from src.config import REPO_ROOT, Settings
from src.models import SharedContext


class IncidentRecord(BaseModel):
    """A finished run, as persisted for the UI history."""

    id: str
    started_at: datetime
    finished_at: datetime
    approved: bool | None
    context: SharedContext


class IncidentRecordSummary(BaseModel):
    """Summarized view of an `IncidentRecord`, used by the history list."""

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
    """Common interface: save and reload finished runs."""

    async def save(self, record: IncidentRecord) -> None: ...

    async def list_records(self, *, limit: int = 20) -> list[IncidentRecordSummary]: ...

    async def get_record(self, run_id: str) -> IncidentRecord | None: ...


class LocalPersistenceStore:
    """One JSON file per run in `path` (offline mode, KB_MODE=local)."""

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
    """Azure Cosmos DB container (deployed mode, `COSMOS_ENDPOINT` set).

    The account, database, and container (partition key `/id`) are
    provisioned by `infra/` (Bicep); this class only reads/writes
    documents via the data plane (role `Cosmos DB Built-in Data
    Contributor`, see SPEC.md section 7).
    """

    def __init__(self, *, endpoint: str, database: str, container: str, credential: object) -> None:
        from azure.cosmos.aio import CosmosClient

        self._client = CosmosClient(endpoint, credential=credential)
        self._database = database
        self._container = container

    def _container_client(self):  # noqa: ANN202 - type lives in azure.cosmos.aio
        return self._client.get_database_client(self._database).get_container_client(self._container)

    async def save(self, record: IncidentRecord) -> None:
        await self._container_client().upsert_item(record.model_dump(mode="json"))

    async def list_records(self, *, limit: int = 20) -> list[IncidentRecordSummary]:
        container = self._container_client()
        records = [
            IncidentRecord.model_validate(item)
            async for item in container.query_items(query="SELECT * FROM c")
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
    """Picks the persistence implementation based on `COSMOS_ENDPOINT`."""

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
