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
        """Yield records created/updated after `cursor` (a unix timestamp).
        `cursor=None` means from the beginning (full backfill)."""

    @abstractmethod
    def search(self, vector: list[float], top_k: int) -> list[ScoredMatch]:
        """Run a similarity search, used only for parity verification."""

    @abstractmethod
    def count(self) -> int:
        """Total records in the collection, for sanity/pre-flight checks."""
