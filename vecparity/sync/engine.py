"""Incremental replication: polls the source's list_changed_since/
list_deleted_since cursor and replays new/updated/deleted records to the
target in batches."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from vecparity.adapters.base import VectorDBAdapter
from vecparity.checkpoint import MigrationCheckpoint
from vecparity.types import VectorRecord


@dataclass
class SyncStats:
    batches: int = 0
    records_synced: int = 0
    records_deleted: int = 0
    records_quarantined: int = 0
    last_cursor: float | None = None
    started_at: float = field(default_factory=time.time)


class SyncEngine:
    """Copies changed and deleted records from `source` to `target`, batch by batch."""

    def __init__(
        self,
        source: VectorDBAdapter,
        target: VectorDBAdapter,
        batch_size: int = 500,
        cursor: float | None = None,
        cursor_ids: set[str] | None = None,
        deleted_cursor_ids: set[str] | None = None,
        max_retries: int = 3,
        retry_backoff: float = 1.0,
        quarantine_path: str | Path | None = None,
    ) -> None:
        self.source = source
        self.target = target
        self.batch_size = batch_size
        self.cursor = cursor
        # Ids already processed at exactly `cursor`'s timestamp, so a
        # re-fetched boundary record (inclusive `>=` query) isn't
        # reprocessed on the next poll. Separate sets for upserts and
        # deletes since they're independent operations against the same id.
        self.cursor_ids = cursor_ids or set()
        self.deleted_cursor_ids = deleted_cursor_ids or set()
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.quarantine_path = Path(quarantine_path) if quarantine_path else None
        self.stats = SyncStats(last_cursor=cursor)

    @classmethod
    def from_checkpoint(
        cls,
        source: VectorDBAdapter,
        target: VectorDBAdapter,
        checkpoint: MigrationCheckpoint,
        batch_size: int = 500,
        max_retries: int = 3,
        retry_backoff: float = 1.0,
        quarantine_path: str | Path | None = None,
    ) -> SyncEngine:
        """Resume where a previous run left off, instead of restarting
        from scratch. Restores the boundary-id sets too, not just the
        raw cursor, so the tie-safe dedup logic survives the restart."""
        engine = cls(
            source,
            target,
            batch_size=batch_size,
            cursor=checkpoint.cursor,
            cursor_ids=set(checkpoint.cursor_ids),
            deleted_cursor_ids=set(checkpoint.deleted_cursor_ids),
            max_retries=max_retries,
            retry_backoff=retry_backoff,
            quarantine_path=quarantine_path,
        )
        engine.stats.records_synced = checkpoint.records_synced
        engine.stats.records_deleted = checkpoint.records_deleted
        return engine

    def checkpoint(
        self, migration_id: str, source_spec: str, target_spec: str
    ) -> MigrationCheckpoint:
        """Snapshot current progress for `CheckpointStore.save()`."""
        return MigrationCheckpoint(
            migration_id=migration_id,
            source=source_spec,
            target=target_spec,
            cursor=self.cursor,
            cursor_ids=set(self.cursor_ids),
            deleted_cursor_ids=set(self.deleted_cursor_ids),
            records_synced=self.stats.records_synced,
            records_deleted=self.stats.records_deleted,
        )

    def _upsert_with_retry(self, batch: list[VectorRecord]) -> None:
        """Upsert a batch, retrying transient failures with exponential
        backoff. A batch that still fails after retries is quarantined
        record-by-record so one bad record doesn't sink the whole batch."""
        for attempt in range(self.max_retries):
            try:
                self.target.upsert(batch)
                return
            except Exception:
                if attempt == self.max_retries - 1:
                    break
                time.sleep(self.retry_backoff * (2**attempt))

        self._quarantine_batch(batch)

    def _quarantine_batch(self, batch: list[VectorRecord]) -> None:
        """Retry the batch one record at a time; anything that still
        fails goes to the quarantine file, everything else still syncs."""
        for record in batch:
            try:
                self.target.upsert([record])
            except Exception as exc:
                self.stats.records_quarantined += 1
                if self.quarantine_path is not None:
                    self.quarantine_path.parent.mkdir(parents=True, exist_ok=True)
                    with self.quarantine_path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps({"id": record.id, "error": str(exc)}) + "\n")

    def _advance(
        self,
        max_seen: float | None,
        boundary_ids: set[str],
        updated_at: float | None,
        record_id: str,
    ) -> tuple[float | None, set[str]]:
        """Track the running max timestamp seen this pass and the set of
        ids sitting exactly at it, so the next poll's cursor stays
        tie-safe."""
        if updated_at is None:
            return max_seen, boundary_ids
        if max_seen is None or updated_at > max_seen:
            return updated_at, {record_id}
        if updated_at == max_seen:
            boundary_ids.add(record_id)
        return max_seen, boundary_ids

    def run_once(self) -> int:
        """Replicate everything changed or deleted since the current
        cursor. Returns the number of records synced (upserted), and
        advances the cursor."""
        prior_cursor = self.cursor
        batch: list[VectorRecord] = []
        synced = 0
        max_seen = prior_cursor
        new_boundary_ids: set[str] = set()

        for record in self.source.list_changed_since(prior_cursor):
            if (
                prior_cursor is not None
                and record.updated_at == prior_cursor
                and record.id in self.cursor_ids
            ):
                continue  # already synced in a prior run at this exact boundary

            max_seen, new_boundary_ids = self._advance(
                max_seen, new_boundary_ids, record.updated_at, record.id
            )
            batch.append(record)
            if len(batch) >= self.batch_size:
                self._upsert_with_retry(batch)
                synced += len(batch)
                self.stats.batches += 1
                batch = []

        if batch:
            self._upsert_with_retry(batch)
            synced += len(batch)
            self.stats.batches += 1

        if max_seen == prior_cursor:
            self.cursor_ids |= new_boundary_ids
        else:
            self.cursor_ids = new_boundary_ids

        max_seen, deleted = self._propagate_deletes(prior_cursor, max_seen)

        self.cursor = max_seen
        self.stats.last_cursor = max_seen
        self.stats.records_synced += synced
        self.stats.records_deleted += deleted
        return synced

    def _propagate_deletes(
        self, prior_cursor: float | None, max_seen: float | None
    ) -> tuple[float | None, int]:
        """Mirror source deletions to the target, using the same
        inclusive-cursor, dedup-by-id boundary tracking as upserts, and
        folding into the same unified `max_seen` the upsert pass computed
        so one cursor covers both streams. A backend without delete
        tracking yields nothing here, which is the documented default,
        not an error."""
        ids_to_delete: list[str] = []
        starting_max = max_seen
        new_boundary_ids: set[str] = set()

        for deleted_id, deleted_at in self.source.list_deleted_since(prior_cursor):
            if (
                prior_cursor is not None
                and deleted_at == prior_cursor
                and deleted_id in self.deleted_cursor_ids
            ):
                continue

            max_seen, new_boundary_ids = self._advance(
                max_seen, new_boundary_ids, deleted_at, deleted_id
            )
            ids_to_delete.append(deleted_id)

        if ids_to_delete:
            self.target.delete(ids_to_delete)

        if max_seen == starting_max:
            self.deleted_cursor_ids |= new_boundary_ids
        else:
            self.deleted_cursor_ids = new_boundary_ids

        return max_seen, len(ids_to_delete)

    def run_until_caught_up(
        self,
        poll_interval: float = 5.0,
        idle_passes: int = 2,
        on_batch: Callable[[], None] | None = None,
    ) -> None:
        """Poll `run_once` until N consecutive passes sync nothing.
        `on_batch`, if given, runs after every pass, so a caller can
        persist a checkpoint mid-run instead of only at the very end."""
        consecutive_idle = 0
        while consecutive_idle < idle_passes:
            synced = self.run_once()
            if on_batch is not None:
                on_batch()
            consecutive_idle = consecutive_idle + 1 if synced == 0 else 0
            if consecutive_idle < idle_passes:
                time.sleep(poll_interval)
