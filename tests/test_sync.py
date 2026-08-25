"""Sync engine tests using two in-memory adapters."""

from __future__ import annotations

import json
import time

from vecparity.adapters.memory import MemoryAdapter
from vecparity.sync.engine import SyncEngine
from vecparity.types import VectorRecord


def test_run_once_copies_all_records_on_first_pass():
    source, target = MemoryAdapter(), MemoryAdapter()
    source.upsert([VectorRecord(id=f"d{i}", vector=[float(i)]) for i in range(10)])

    engine = SyncEngine(source, target, batch_size=3)
    synced = engine.run_once()

    assert synced == 10
    assert target.count() == 10


def test_run_once_is_incremental_on_second_pass():
    source, target = MemoryAdapter(), MemoryAdapter()
    source.upsert([VectorRecord(id="d1", vector=[1.0])])

    engine = SyncEngine(source, target)
    engine.run_once()

    # Nothing new since the cursor advanced -> second pass syncs 0.
    assert engine.run_once() == 0

    # A genuinely new record after the cursor gets picked up.
    time.sleep(0.01)
    source.upsert([VectorRecord(id="d2", vector=[2.0])])
    assert engine.run_once() == 1
    assert target.count() == 2


def test_run_until_caught_up_stops_after_idle_passes():
    source, target = MemoryAdapter(), MemoryAdapter()
    source.upsert([VectorRecord(id=f"d{i}", vector=[float(i)]) for i in range(5)])

    engine = SyncEngine(source, target)
    engine.run_until_caught_up(poll_interval=0, idle_passes=2)

    assert target.count() == 5


def test_boundary_tie_records_are_not_skipped_or_resynced():
    # A record sharing its timestamp with the cursor used to be silently
    # dropped by a strict `>` comparison; the fix is inclusive `>=` plus
    # dedup-by-id, so nothing at the boundary is lost or reprocessed.
    source, target = MemoryAdapter(), MemoryAdapter()
    source.upsert(
        [
            VectorRecord(id="a", vector=[1.0], updated_at=100.0),
            VectorRecord(id="b", vector=[2.0], updated_at=100.0),
        ]
    )
    engine = SyncEngine(source, target)
    assert engine.run_once() == 2
    assert engine.cursor == 100.0
    assert engine.cursor_ids == {"a", "b"}

    # A third record lands at the exact same timestamp after the cursor
    # already advanced there.
    source.upsert([VectorRecord(id="c", vector=[3.0], updated_at=100.0)])
    assert engine.run_once() == 1
    assert target.count() == 3
    assert engine.cursor_ids == {"a", "b", "c"}

    # Nothing new: a/b/c should not be resynced.
    assert engine.run_once() == 0


def test_delete_propagates_to_target():
    source, target = MemoryAdapter(), MemoryAdapter()
    source.upsert([VectorRecord(id="a", vector=[1.0]), VectorRecord(id="b", vector=[2.0])])

    engine = SyncEngine(source, target)
    engine.run_once()
    assert target.count() == 2

    source.delete(["a"])
    engine.run_once()

    assert target.get("a") is None
    assert target.count() == 1
    assert engine.stats.records_deleted == 1

    # A repeat poll shouldn't reissue the same delete.
    engine.run_once()
    assert engine.stats.records_deleted == 1


class _FlakyAdapter(MemoryAdapter):
    """Always fails to upsert one specific id, for quarantine tests."""

    def __init__(self, bad_id: str) -> None:
        super().__init__()
        self.bad_id = bad_id

    def upsert(self, records: list[VectorRecord]) -> None:
        if any(r.id == self.bad_id for r in records):
            raise RuntimeError("simulated permanent failure")
        super().upsert(records)


def test_quarantine_isolates_bad_record(tmp_path):
    source = MemoryAdapter()
    target = _FlakyAdapter(bad_id="bad")
    source.upsert(
        [
            VectorRecord(id="good1", vector=[1.0]),
            VectorRecord(id="bad", vector=[2.0]),
            VectorRecord(id="good2", vector=[3.0]),
        ]
    )
    quarantine_file = tmp_path / "failures.jsonl"

    engine = SyncEngine(
        source, target, max_retries=1, retry_backoff=0, quarantine_path=quarantine_file
    )
    engine.run_once()

    assert target.get("good1") is not None
    assert target.get("good2") is not None
    assert target.get("bad") is None
    assert engine.stats.records_quarantined == 1

    lines = quarantine_file.read_text().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["id"] == "bad"


class _TransientlyFlakyAdapter(MemoryAdapter):
    """Fails the first N upserts, then succeeds, for retry tests."""

    def __init__(self, fail_times: int) -> None:
        super().__init__()
        self.fail_times = fail_times
        self.attempts = 0

    def upsert(self, records: list[VectorRecord]) -> None:
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise RuntimeError("simulated transient failure")
        super().upsert(records)


def test_retry_recovers_from_transient_failure():
    source = MemoryAdapter()
    target = _TransientlyFlakyAdapter(fail_times=2)
    source.upsert([VectorRecord(id="a", vector=[1.0])])

    engine = SyncEngine(source, target, max_retries=3, retry_backoff=0)
    synced = engine.run_once()

    assert synced == 1
    assert target.count() == 1
    assert engine.stats.records_quarantined == 0
