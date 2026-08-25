"""Durable migration checkpoints: persists a SyncEngine's cursor and
boundary-id state to a local SQLite file, so a crashed or interrupted
migration can resume instead of restarting from scratch.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CHECKPOINT_PATH = Path.home() / ".vecparity" / "checkpoints.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoints (
    migration_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    cursor REAL,
    cursor_ids TEXT NOT NULL DEFAULT '[]',
    deleted_cursor_ids TEXT NOT NULL DEFAULT '[]',
    records_synced INTEGER NOT NULL DEFAULT 0,
    records_deleted INTEGER NOT NULL DEFAULT 0,
    last_batch_at REAL
)
"""


@dataclass
class MigrationCheckpoint:
    migration_id: str
    source: str
    target: str
    cursor: float | None = None
    cursor_ids: set[str] = field(default_factory=set)
    deleted_cursor_ids: set[str] = field(default_factory=set)
    records_synced: int = 0
    records_deleted: int = 0
    last_batch_at: float | None = None


class CheckpointStore:
    """SQLite-backed store, one row per (source, target) migration pair."""

    def __init__(self, path: str | Path = DEFAULT_CHECKPOINT_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def load(self, migration_id: str) -> MigrationCheckpoint | None:
        row = self._conn.execute(
            "SELECT migration_id, source, target, cursor, cursor_ids, "
            "deleted_cursor_ids, records_synced, records_deleted, last_batch_at "
            "FROM checkpoints WHERE migration_id = ?",
            (migration_id,),
        ).fetchone()
        if row is None:
            return None
        return MigrationCheckpoint(
            migration_id=row[0],
            source=row[1],
            target=row[2],
            cursor=row[3],
            cursor_ids=set(json.loads(row[4])),
            deleted_cursor_ids=set(json.loads(row[5])),
            records_synced=row[6],
            records_deleted=row[7],
            last_batch_at=row[8],
        )

    def save(self, checkpoint: MigrationCheckpoint) -> None:
        checkpoint.last_batch_at = time.time()
        self._conn.execute(
            """
            INSERT INTO checkpoints
                (migration_id, source, target, cursor, cursor_ids,
                 deleted_cursor_ids, records_synced, records_deleted, last_batch_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(migration_id) DO UPDATE SET
                cursor = excluded.cursor,
                cursor_ids = excluded.cursor_ids,
                deleted_cursor_ids = excluded.deleted_cursor_ids,
                records_synced = excluded.records_synced,
                records_deleted = excluded.records_deleted,
                last_batch_at = excluded.last_batch_at
            """,
            (
                checkpoint.migration_id,
                checkpoint.source,
                checkpoint.target,
                checkpoint.cursor,
                json.dumps(sorted(checkpoint.cursor_ids)),
                json.dumps(sorted(checkpoint.deleted_cursor_ids)),
                checkpoint.records_synced,
                checkpoint.records_deleted,
                checkpoint.last_batch_at,
            ),
        )
        self._conn.commit()

    def delete(self, migration_id: str) -> None:
        self._conn.execute("DELETE FROM checkpoints WHERE migration_id = ?", (migration_id,))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
