"""CheckpointStore tests, and SyncEngine's checkpoint round-trip."""

from __future__ import annotations

from vecparity.adapters.memory import MemoryAdapter
from vecparity.checkpoint import CheckpointStore, MigrationCheckpoint
from vecparity.sync.engine import SyncEngine
from vecparity.types import VectorRecord


def test_save_and_load_round_trips_all_fields(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints.db")
    cp = MigrationCheckpoint(
        migration_id="a=>b",
        source="a",
        target="b",
        cursor=100.0,
        cursor_ids={"x", "y"},
        deleted_cursor_ids={"z"},
        records_synced=5,
        records_deleted=1,
    )
    store.save(cp)

    loaded = store.load("a=>b")
    assert loaded is not None
    assert loaded.cursor == 100.0
    assert loaded.cursor_ids == {"x", "y"}
    assert loaded.deleted_cursor_ids == {"z"}
    assert loaded.records_synced == 5
    assert loaded.records_deleted == 1
    assert loaded.last_batch_at is not None  # stamped by save()


def test_load_missing_migration_returns_none(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints.db")
    assert store.load("nope") is None


def test_save_overwrites_existing_checkpoint(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints.db")
    store.save(MigrationCheckpoint(migration_id="a=>b", source="a", target="b", cursor=1.0))
    store.save(MigrationCheckpoint(migration_id="a=>b", source="a", target="b", cursor=2.0))

    loaded = store.load("a=>b")
    assert loaded is not None
    assert loaded.cursor == 2.0


def test_clear_removes_checkpoint(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints.db")
    store.save(MigrationCheckpoint(migration_id="a=>b", source="a", target="b", cursor=1.0))
    store.delete("a=>b")
    assert store.load("a=>b") is None


def test_sync_engine_resumes_from_checkpoint(tmp_path):
    source, target = MemoryAdapter(), MemoryAdapter()
    source.upsert(
        [
            VectorRecord(id="a", vector=[1.0], updated_at=100.0),
            VectorRecord(id="b", vector=[2.0], updated_at=100.0),
        ]
    )

    store = CheckpointStore(tmp_path / "checkpoints.db")
    engine = SyncEngine(source, target)
    engine.run_once()
    store.save(engine.checkpoint("a=>b", "a", "b"))

    # Fresh process, fresh engine: rebuild from the saved checkpoint.
    saved = store.load("a=>b")
    assert saved is not None
    resumed = SyncEngine.from_checkpoint(source, target, saved)

    assert resumed.cursor == 100.0
    assert resumed.cursor_ids == {"a", "b"}
    assert resumed.stats.records_synced == 2

    # A tie-boundary record arrives after the "restart"; still not skipped.
    source.upsert([VectorRecord(id="c", vector=[3.0], updated_at=100.0)])
    assert resumed.run_once() == 1
    assert target.count() == 3
