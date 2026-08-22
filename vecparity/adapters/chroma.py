"""Chroma adapter. Requires the `chroma` extra.

Chroma accepts arbitrary string ids natively and has a native
`upsert()`, so no id-mapping trick is needed. Assumes a cosine-space
collection; `query()` distance is converted to a similarity score via
`1 - distance`. The `# type: ignore` comments below are for chromadb's
type stubs being narrower than its actual runtime API.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from vecparity.adapters.base import VectorDBAdapter
from vecparity.types import ScoredMatch, VectorRecord

try:
    from chromadb.api.models.Collection import Collection
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "ChromaAdapter requires the 'chroma' extra: pip install vecparity[chroma]"
    ) from e


class ChromaAdapter(VectorDBAdapter):
    def __init__(
        self,
        collection: Collection,
        updated_at_field: str = "updated_at",
        page_size: int = 256,
    ) -> None:
        self.collection = collection
        self.updated_at_field = updated_at_field
        self.page_size = page_size

    def get(self, id: str) -> VectorRecord | None:
        result = self.collection.get(ids=[id], include=["embeddings", "metadatas"])
        ids = result["ids"]
        if not ids:
            return None
        embeddings = result["embeddings"]
        metadatas = result["metadatas"]
        assert embeddings is not None and metadatas is not None  # guaranteed by include=
        return self._to_record(ids[0], embeddings[0], dict(metadatas[0] or {}))

    def upsert(self, records: list[VectorRecord]) -> None:
        self.collection.upsert(
            ids=[r.id for r in records],
            embeddings=[r.vector for r in records],  # type: ignore[arg-type]
            metadatas=[{**r.metadata, self.updated_at_field: r.updated_at} for r in records],
        )

    def delete(self, ids: list[str]) -> None:
        self.collection.delete(ids=ids)

    def list_changed_since(self, cursor: float | None) -> Iterator[VectorRecord]:
        where = {self.updated_at_field: {"$gt": cursor}} if cursor is not None else None
        offset = 0
        while True:
            result = self.collection.get(
                where=where,  # type: ignore[arg-type]
                limit=self.page_size,
                offset=offset,
                include=["embeddings", "metadatas"],
            )
            ids = result["ids"]
            if not ids:
                break
            embeddings = result["embeddings"]
            metadatas = result["metadatas"]
            assert embeddings is not None and metadatas is not None
            for id, vector, metadata in zip(ids, embeddings, metadatas, strict=True):
                yield self._to_record(id, vector, dict(metadata or {}))
            if len(ids) < self.page_size:
                break
            offset += len(ids)

    def search(self, vector: list[float], top_k: int) -> list[ScoredMatch]:
        result = self.collection.query(
            query_embeddings=[vector],  # type: ignore[arg-type]
            n_results=top_k,
            include=["distances", "metadatas"],
        )
        raw_ids = result["ids"][0]
        distances = result["distances"]
        metadatas = result["metadatas"]
        assert distances is not None and metadatas is not None
        matches = []
        for id, distance, metadata in zip(raw_ids, distances[0], metadatas[0], strict=True):
            meta = dict(metadata or {})
            meta.pop(self.updated_at_field, None)
            matches.append(ScoredMatch(id=id, score=1.0 - distance, metadata=meta))
        return matches

    def count(self) -> int:
        return self.collection.count()

    def _to_record(self, id: str, vector: Any, metadata: dict[str, Any]) -> VectorRecord:
        metadata = dict(metadata)
        updated_at = metadata.pop(self.updated_at_field, None)
        return VectorRecord(
            id=id,
            vector=[float(x) for x in vector],
            metadata=metadata,
            updated_at=updated_at,
        )
