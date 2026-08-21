"""Pinecone adapter.

Requires the `pinecone` extra: `pip install vecparity[pinecone]`.

Change tracking: like Qdrant, Pinecone has no native change feed exposed
through the client used here, so `list_changed_since` scrolls the index
via `list()` + `fetch()` and filters on a metadata field (default
`updated_at`) the caller maintains on writes.

Note: Pinecone's `list()` only returns ids (no vectors/metadata), so
`list_changed_since` has to `fetch()` each page of ids separately — this
makes it the slowest adapter to backfill from. Fine for its intended use
(migrating *out of* Pinecone), less fine as a sync source for anything
long-running.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from vecparity.adapters.base import VectorDBAdapter
from vecparity.types import ScoredMatch, VectorRecord

try:
    from pinecone import Pinecone
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "PineconeAdapter requires the 'pinecone' extra: pip install vecparity[pinecone]"
    ) from e


class PineconeAdapter(VectorDBAdapter):
    def __init__(
        self,
        client: Pinecone,
        index_name: str,
        namespace: str = "",
        updated_at_field: str = "updated_at",
        fetch_batch_size: int = 100,
    ) -> None:
        self.index = client.Index(index_name)
        self.namespace = namespace
        self.updated_at_field = updated_at_field
        self.fetch_batch_size = fetch_batch_size

    def get(self, id: str) -> VectorRecord | None:
        result = self.index.fetch(ids=[id], namespace=self.namespace)
        vectors = result.vectors if hasattr(result, "vectors") else result.get("vectors", {})
        if id not in vectors:
            return None
        return self._to_record(id, vectors[id])

    def upsert(self, records: list[VectorRecord]) -> None:
        vectors = []
        for r in records:
            metadata: dict[str, Any] = {**r.metadata, self.updated_at_field: r.updated_at}
            vectors.append({"id": r.id, "values": r.vector, "metadata": metadata})
        self.index.upsert(vectors=vectors, namespace=self.namespace)

    def delete(self, ids: list[str]) -> None:
        self.index.delete(ids=ids, namespace=self.namespace)

    def list_changed_since(self, cursor: float | None) -> Iterator[VectorRecord]:
        id_batch: list[str] = []
        for id in self.index.list(namespace=self.namespace):
            id_batch.append(id)
            if len(id_batch) >= self.fetch_batch_size:
                yield from self._fetch_and_filter(id_batch, cursor)
                id_batch = []
        if id_batch:
            yield from self._fetch_and_filter(id_batch, cursor)

    def search(self, vector: list[float], top_k: int) -> list[ScoredMatch]:
        result = self.index.query(
            vector=vector, top_k=top_k, namespace=self.namespace, include_metadata=True
        )
        matches = result.matches if hasattr(result, "matches") else result.get("matches", [])
        return [
            ScoredMatch(id=m.id, score=m.score, metadata=dict(m.metadata or {})) for m in matches
        ]

    def count(self) -> int:
        stats = self.index.describe_index_stats()
        namespaces = (
            stats.namespaces if hasattr(stats, "namespaces") else stats.get("namespaces", {})
        )
        ns = namespaces.get(self.namespace)
        if ns is None:
            return 0
        count = ns.vector_count if hasattr(ns, "vector_count") else ns.get("vector_count", 0)
        return int(count)

    def _fetch_and_filter(self, ids: list[str], cursor: float | None) -> Iterator[VectorRecord]:
        result = self.index.fetch(ids=ids, namespace=self.namespace)
        vectors = result.vectors if hasattr(result, "vectors") else result.get("vectors", {})
        for id, v in vectors.items():
            record = self._to_record(id, v)
            if cursor is None or (record.updated_at or 0) > cursor:
                yield record

    def _to_record(self, id: str, v: Any) -> VectorRecord:
        values = v.values if hasattr(v, "values") else v["values"]
        metadata = dict(v.metadata if hasattr(v, "metadata") else v.get("metadata", {}) or {})
        updated_at = metadata.pop(self.updated_at_field, None)
        return VectorRecord(id=id, vector=list(values), metadata=metadata, updated_at=updated_at)
