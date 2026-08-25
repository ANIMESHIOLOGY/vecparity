"""CLI tests against the in-memory backend, no docker required.

`_load_adapter` is monkeypatched to hand back fixed MemoryAdapter
instances instead of fresh ones per call, so state actually persists
across the separate CLI invocations these tests make, the way a real
long-running process's adapters would.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from vecparity import cli
from vecparity.adapters.memory import MemoryAdapter
from vecparity.checkpoint import CheckpointStore, MigrationCheckpoint
from vecparity.types import VectorRecord

runner = CliRunner()


@pytest.fixture
def adapters(monkeypatch):
    source, target = MemoryAdapter(), MemoryAdapter()
    by_spec = {"memory://a": source, "memory://b": target}
    monkeypatch.setattr(cli, "_load_adapter", lambda spec: by_spec[spec])
    return source, target


def _invoke(*args):
    return runner.invoke(cli.app, [str(a) for a in args])


def test_migrate_run_syncs_and_records_syncing_status(adapters, tmp_path):
    source, target = adapters
    source.upsert([VectorRecord(id="d1", vector=[1.0])])
    ckpt = tmp_path / "checkpoints.db"

    result = _invoke(
        "migrate", "run", "--from", "memory://a", "--to", "memory://b", "--checkpoint-file", ckpt
    )

    assert result.exit_code == 0, result.output
    assert target.count() == 1
    cp = CheckpointStore(ckpt).load("memory://a=>memory://b")
    assert cp is not None
    assert cp.status == "syncing"
    assert cp.records_synced == 1


def test_migrate_pause_requires_a_syncing_migration(adapters, tmp_path):
    ckpt = tmp_path / "checkpoints.db"

    result = _invoke(
        "migrate", "pause", "--from", "memory://a", "--to", "memory://b", "--checkpoint-file", ckpt
    )

    assert result.exit_code != 0
    assert "No migration recorded" in result.output


def test_migrate_pause_sets_pause_requested(adapters, tmp_path):
    ckpt = tmp_path / "checkpoints.db"
    store = CheckpointStore(ckpt)
    store.save(
        MigrationCheckpoint(
            migration_id="memory://a=>memory://b",
            source="memory://a",
            target="memory://b",
            status="syncing",
        )
    )

    result = _invoke(
        "migrate", "pause", "--from", "memory://a", "--to", "memory://b", "--checkpoint-file", ckpt
    )

    assert result.exit_code == 0, result.output
    assert store.load("memory://a=>memory://b").status == "pause_requested"


def test_migrate_cancel_blocks_resume_without_fresh(adapters, tmp_path):
    source, target = adapters
    ckpt = tmp_path / "checkpoints.db"
    store = CheckpointStore(ckpt)
    store.save(
        MigrationCheckpoint(
            migration_id="memory://a=>memory://b",
            source="memory://a",
            target="memory://b",
            status="syncing",
        )
    )

    cancel_result = _invoke(
        "migrate", "cancel", "--from", "memory://a", "--to", "memory://b", "--checkpoint-file", ckpt
    )
    assert cancel_result.exit_code == 0
    assert store.load("memory://a=>memory://b").status == "cancelled"

    rerun_result = _invoke(
        "migrate", "run", "--from", "memory://a", "--to", "memory://b", "--checkpoint-file", ckpt
    )
    assert rerun_result.exit_code != 0
    assert "cancelled" in rerun_result.output

    fresh_result = _invoke(
        "migrate",
        "run",
        "--from",
        "memory://a",
        "--to",
        "memory://b",
        "--checkpoint-file",
        ckpt,
        "--fresh",
    )
    assert fresh_result.exit_code == 0, fresh_result.output


def test_cutover_requires_a_passing_parity_check(adapters, tmp_path):
    source, target = adapters
    records = [VectorRecord(id=f"d{i}", vector=[float(i), float(i) + 1, 0.0]) for i in range(5)]
    source.upsert(records)
    target.upsert(records)  # target already matches, so parity will pass

    ckpt = tmp_path / "checkpoints.db"
    store = CheckpointStore(ckpt)
    store.save(
        MigrationCheckpoint(
            migration_id="memory://a=>memory://b",
            source="memory://a",
            target="memory://b",
            status="syncing",
        )
    )

    queries_file = tmp_path / "queries.json"
    queries_file.write_text(json.dumps([{"query_id": "d0", "top_k": 3}]))

    result = _invoke(
        "cutover",
        "--from",
        "memory://a",
        "--to",
        "memory://b",
        "--queries",
        queries_file,
        "--checkpoint-file",
        ckpt,
    )

    assert result.exit_code == 0, result.output
    assert "Cutover complete" in result.output
    assert store.load("memory://a=>memory://b").status == "cut_over"


def test_cutover_fails_and_leaves_status_unchanged_on_bad_parity(adapters, tmp_path):
    source, target = adapters
    records = [
        VectorRecord(id=f"d{i}", vector=[float(i), float(i) + 1, 0.0], updated_at=100.0)
        for i in range(5)
    ]
    source.upsert(records)
    # Checkpoint's cursor is already past these records' timestamp, so
    # cutover's own "final sync" pass (from this checkpoint) won't pick
    # them up either: target stays empty and the gap surfaces in the
    # parity check instead of being silently closed first.

    ckpt = tmp_path / "checkpoints.db"
    store = CheckpointStore(ckpt)
    store.save(
        MigrationCheckpoint(
            migration_id="memory://a=>memory://b",
            source="memory://a",
            target="memory://b",
            status="syncing",
            cursor=200.0,
        )
    )

    queries_file = tmp_path / "queries.json"
    queries_file.write_text(json.dumps([{"query_id": "d0", "top_k": 3}]))

    result = _invoke(
        "cutover",
        "--from",
        "memory://a",
        "--to",
        "memory://b",
        "--queries",
        queries_file,
        "--checkpoint-file",
        ckpt,
    )

    assert result.exit_code != 0
    assert "aborted" in result.output.lower()
    assert store.load("memory://a=>memory://b").status == "syncing"


def test_rollback_requires_a_cut_over_migration(adapters, tmp_path):
    ckpt = tmp_path / "checkpoints.db"
    store = CheckpointStore(ckpt)
    store.save(
        MigrationCheckpoint(
            migration_id="memory://a=>memory://b",
            source="memory://a",
            target="memory://b",
            status="syncing",
        )
    )

    result = _invoke(
        "rollback", "--from", "memory://a", "--to", "memory://b", "--checkpoint-file", ckpt
    )

    assert result.exit_code != 0
    assert store.load("memory://a=>memory://b").status == "syncing"


def test_rollback_after_cutover(adapters, tmp_path):
    ckpt = tmp_path / "checkpoints.db"
    store = CheckpointStore(ckpt)
    store.save(
        MigrationCheckpoint(
            migration_id="memory://a=>memory://b",
            source="memory://a",
            target="memory://b",
            status="cut_over",
        )
    )

    result = _invoke(
        "rollback", "--from", "memory://a", "--to", "memory://b", "--checkpoint-file", ckpt
    )

    assert result.exit_code == 0, result.output
    assert store.load("memory://a=>memory://b").status == "rolled_back"


def test_migrate_status_prints_persisted_state(adapters, tmp_path):
    ckpt = tmp_path / "checkpoints.db"
    store = CheckpointStore(ckpt)
    store.save(
        MigrationCheckpoint(
            migration_id="memory://a=>memory://b",
            source="memory://a",
            target="memory://b",
            status="verified",
            records_synced=42,
        )
    )

    result = _invoke(
        "migrate", "status", "--from", "memory://a", "--to", "memory://b", "--checkpoint-file", ckpt
    )

    assert result.exit_code == 0
    assert "status: verified" in result.output
    assert "records_synced: 42" in result.output
