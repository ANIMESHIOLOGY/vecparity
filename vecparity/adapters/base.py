"""The adapter protocol every backend implements.

Deliberately minimal: five operations is enough to migrate and verify, and
keeping it small is what keeps this a migration tool instead of a leaky
permanent ORM.
"""

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
        """Yield records created/updated after `cursor` (a unix timestamp).

        `cursor=None` means "from the beginning" (full backfill). This is
        the primitive the incremental sync engine polls to avoid re-copying
        the whole collection on every pass. Backends without native change
        feeds should implement this via an `updated_at` metadata field.
        """

    @abstractmethod
    def search(self, vector: list[float], top_k: int) -> list[ScoredMatch]:
        """Run a similarity search — used only for parity verification,
        never exposed as a general query API by design."""

    @abstractmethod
    def count(self) -> int:
        """Total records in the collection, for sanity/pre-flight checks."""
