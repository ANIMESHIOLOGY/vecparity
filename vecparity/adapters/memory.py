"""In-memory adapter: used by tests and as a runnable reference implementation.

Also handy for `vecparity migrate --from memory://fixture.json --to qdrant`
style dry runs while wiring up a new backend.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import numpy as np

from vecparity.adapters.base import VectorDBAdapter
from vecparity.types import ScoredMatch, VectorRecord


class MemoryAdapter(VectorDBAdapter):
    def __init__(self) -> None:
        self._store: dict[str, VectorRecord] = {}

    def get(self, id: str) -> VectorRecord | None:
        return self._store.get(id)

    def upsert(self, records: list[VectorRecord]) -> None:
        now = time.time()
        for r in records:
            if r.updated_at is None:
                r = r.model_copy(update={"updated_at": now})
            self._store[r.id] = r

    def delete(self, ids: list[str]) -> None:
        for id in ids:
            self._store.pop(id, None)

    def list_changed_since(self, cursor: float | None) -> Iterator[VectorRecord]:
        for r in self._store.values():
            if cursor is None or (r.updated_at or 0) > cursor:
                yield r

    def search(self, vector: list[float], top_k: int) -> list[ScoredMatch]:
        if not self._store:
            return []
        q = np.asarray(vector, dtype=np.float32)
        q_norm = q / (np.linalg.norm(q) + 1e-12)
        scored: list[ScoredMatch] = []
        for r in self._store.values():
            v = r.as_array()
            v_norm = v / (np.linalg.norm(v) + 1e-12)
            score = float(np.dot(q_norm, v_norm))
            scored.append(ScoredMatch(id=r.id, score=score, metadata=r.metadata))
        scored.sort(key=lambda m: m.score, reverse=True)
        return scored[:top_k]

    def count(self) -> int:
        return len(self._store)
