"""In-memory adapter: used by tests and as a reference implementation."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import numpy as np

from vecparity.adapters.base import VectorDBAdapter
from vecparity.types import ScoredMatch, VectorRecord


class MemoryAdapter(VectorDBAdapter):
    def __init__(self) -> None:
        self._store: dict[str, VectorRecord] = {}
        self._tombstones: dict[str, float] = {}

    def get(self, id: str) -> VectorRecord | None:
        return self._store.get(id)

    def upsert(self, records: list[VectorRecord]) -> None:
        now = time.time()
        for r in records:
            if r.updated_at is None:
                r = r.model_copy(update={"updated_at": now})
            self._store[r.id] = r
            self._tombstones.pop(r.id, None)

    def delete(self, ids: list[str]) -> None:
        now = time.time()
        for id in ids:
            if self._store.pop(id, None) is not None:
                self._tombstones[id] = now

    def list_changed_since(self, cursor: float | None) -> Iterator[VectorRecord]:
        for r in self._store.values():
            if cursor is None or (r.updated_at or 0) >= cursor:
                yield r

    def list_deleted_since(self, cursor: float | None) -> Iterator[tuple[str, float]]:
        for id, deleted_at in self._tombstones.items():
            if cursor is None or deleted_at >= cursor:
                yield id, deleted_at

    def search(
        self, vector: list[float], top_k: int, filter: dict[str, Any] | None = None
    ) -> list[ScoredMatch]:
        if not self._store:
            return []
        q = np.asarray(vector, dtype=np.float32)
        q_norm = q / (np.linalg.norm(q) + 1e-12)
        scored: list[ScoredMatch] = []
        for r in self._store.values():
            if filter is not None and any(r.metadata.get(k) != v for k, v in filter.items()):
                continue
            v = r.as_array()
            v_norm = v / (np.linalg.norm(v) + 1e-12)
            score = float(np.dot(q_norm, v_norm))
            scored.append(ScoredMatch(id=r.id, score=score, metadata=r.metadata))
        scored.sort(key=lambda m: m.score, reverse=True)
        return scored[:top_k]

    def count(self) -> int:
        return len(self._store)
