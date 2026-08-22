"""Incremental replication: the "live" in live migration.

Polls the source adapter's `list_changed_since` cursor and replays new/
updated records to the target in batches, so a migration can run
alongside a live app instead of requiring a maintenance window. Callers
drive the polling loop themselves (`run_once` / `run_forever`) so this
stays a library, not a daemon that assumes a particular scheduler.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from vecparity.adapters.base import VectorDBAdapter
from vecparity.types import VectorRecord


@dataclass
class SyncStats:
    batches: int = 0
    records_synced: int = 0
    last_cursor: float | None = None
    started_at: float = field(default_factory=time.time)


class SyncEngine:
    """Copies changed records from `source` to `target`, batch by batch."""

    def __init__(
        self,
        source: VectorDBAdapter,
        target: VectorDBAdapter,
        batch_size: int = 500,
        cursor: float | None = None,
    ) -> None:
        self.source = source
        self.target = target
        self.batch_size = batch_size
        self.cursor = cursor
        self.stats = SyncStats(last_cursor=cursor)

    def run_once(self) -> int:
        """Replicate everything changed since the current cursor.

        Returns the number of records synced this pass. Advances the
        cursor to the max `updated_at` seen, so the next call only picks
        up new changes. This is what makes repeated calls (e.g. on a
        polling loop) incremental rather than full re-copies.
        """
        batch: list[VectorRecord] = []
        synced = 0
        max_seen = self.cursor

        for record in self.source.list_changed_since(self.cursor):
            batch.append(record)
            if record.updated_at is not None:
                max_seen = max(max_seen or 0, record.updated_at)
            if len(batch) >= self.batch_size:
                self.target.upsert(batch)
                synced += len(batch)
                self.stats.batches += 1
                batch = []

        if batch:
            self.target.upsert(batch)
            synced += len(batch)
            self.stats.batches += 1

        self.cursor = max_seen
        self.stats.last_cursor = max_seen
        self.stats.records_synced += synced
        return synced

    def run_until_caught_up(self, poll_interval: float = 5.0, idle_passes: int = 2) -> None:
        """Poll `run_once` until N consecutive passes sync nothing.

        Useful for a one-shot "catch up then stop" migration rather than
        an indefinitely running daemon; call this right before cutover.
        """
        consecutive_idle = 0
        while consecutive_idle < idle_passes:
            synced = self.run_once()
            consecutive_idle = consecutive_idle + 1 if synced == 0 else 0
            if consecutive_idle < idle_passes:
                time.sleep(poll_interval)
