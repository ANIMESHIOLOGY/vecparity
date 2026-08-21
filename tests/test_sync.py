"""Sync engine tests using two in-memory adapters."""

from __future__ import annotations

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
