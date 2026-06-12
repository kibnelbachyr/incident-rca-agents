# Copyright (c) Microsoft. All rights reserved.

"""Tests de `LocalPersistenceStore` (mode hors-ligne, KB_MODE=local)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from src.models import Incident, RootCauseHypothesis, SharedContext
from src.tools.persistence import IncidentRecord, LocalPersistenceStore


def _sample_record(run_id: str) -> IncidentRecord:
    context = SharedContext(
        raw_logs="...",
        incident=Incident(
            titre="Pic d'echecs de paiement",
            severite="SEV-1",
            services=["payment-api", "db-pool"],
            fenetre="14:23 -> en cours",
            symptomes=["echec de persistance des transactions"],
        ),
        root_cause=RootCauseHypothesis(
            cause="max_pool_size reduit de 40 a 20",
            raisonnement="...",
            confiance=0.88,
            preuves_manquantes=[],
        ),
        approved=True,
    )
    now = datetime.now(UTC)
    return IncidentRecord(id=run_id, started_at=now, finished_at=now, approved=True, context=context)


async def test_save_then_get_record_roundtrip(tmp_path: Path) -> None:
    store = LocalPersistenceStore(tmp_path)
    record = _sample_record("run-1")

    await store.save(record)
    loaded = await store.get_record("run-1")

    assert loaded is not None
    assert loaded.id == "run-1"
    assert loaded.context.incident is not None
    assert loaded.context.incident.titre == "Pic d'echecs de paiement"
    assert loaded.context.root_cause is not None
    assert loaded.context.root_cause.confiance == 0.88


async def test_get_record_missing_returns_none(tmp_path: Path) -> None:
    store = LocalPersistenceStore(tmp_path)

    assert await store.get_record("does-not-exist") is None


async def test_list_records_summarizes_and_limits(tmp_path: Path) -> None:
    store = LocalPersistenceStore(tmp_path)
    for i in range(3):
        await store.save(_sample_record(f"run-{i}"))

    summaries = await store.list_records(limit=2)

    assert len(summaries) == 2
    for summary in summaries:
        assert summary.titre == "Pic d'echecs de paiement"
        assert summary.severite == "SEV-1"
        assert summary.cause == "max_pool_size reduit de 40 a 20"
        assert summary.confiance == 0.88
        assert summary.approved is True


async def test_list_records_empty_when_directory_missing(tmp_path: Path) -> None:
    store = LocalPersistenceStore(tmp_path / "does-not-exist")

    assert await store.list_records() == []
