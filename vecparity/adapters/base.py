"""The adapter protocol every backend implements. Deliberately minimal."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from vecparity.types import ScoredMatch, VectorRecord


class VectorDBAdapter(ABC):
    """Backend-agnostic read/write interface for one vector collection."""

    @abstractmethod
    def get(self, id: str) -> VectorRecord | None:
        """Fetch a single record by id, or None if it doesn't exist."""

    @abstractmethod
    def upsert(self, records: list[VectorRecord]) -> None:
        """Insert or overwrite records, batched by the caller."""

    @abstractmethod
    def delete(self, ids: list[str]) -> None:
        """Remove records by id."""

    @abstractmethod
    def list_changed_since(self, cursor: float | None) -> Iterator[VectorRecord]:
        """Yield records created/updated at or after `cursor` (a unix
        timestamp), inclusive. `cursor=None` means from the beginning
        (full backfill).

        Inclusive (`>=`), not exclusive (`>`), on purpose: `SyncEngine`
        relies on this to avoid silently dropping a record that shares
        its timestamp with the previous cursor value but wasn't visible
        yet when that boundary was set. `SyncEngine` deduplicates the
        resulting re-fetched boundary records itself.
        """

    @abstractmethod
    def search(self, vector: list[float], top_k: int) -> list[ScoredMatch]:
        """Run a similarity search, used only for parity verification."""

    @abstractmethod
    def count(self) -> int:
        """Total records in the collection, for sanity/pre-flight checks."""

    def list_deleted_since(self, cursor: float | None) -> Iterator[tuple[str, float]]:
        """Yield (id, deleted_at) pairs for records deleted at or after
        `cursor`, inclusive, for live delete propagation.

        Optional, not abstract: `list_changed_since` alone has no way to
        discover a source deletion (a delete leaves no record behind for
        it to yield), so `SyncEngine` calls this when a backend provides
        it and propagates the deletes to the target. Backends without a
        tombstone/change-log mechanism can leave this unimplemented;
        `SyncEngine` treats an empty default as "deletes aren't tracked
        for this source," not an error.

        Returns a timestamp per id, not bare ids, so `SyncEngine` can run
        the same inclusive-cursor, dedup-by-id boundary tracking it uses
        for `list_changed_since`, and advance one unified cursor across
        both upserts and deletes.
        """
        return iter(())
