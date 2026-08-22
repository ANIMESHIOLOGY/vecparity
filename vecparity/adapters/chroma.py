"""Chroma adapter.

Requires the `chroma` extra: `pip install vecparity[chroma]`.

Simplest of the adapters: Chroma accepts arbitrary string ids natively
(no UUID/int restriction like Qdrant or Weaviate) and has a native
`upsert()`, so there's no id-mapping trick or exists-check-then-write
dance needed here.

Change tracking: like Qdrant/Pinecone, Chroma has no native change
feed, so `list_changed_since` pages through `get(where=...)` filtered
on a metadata field (default `updated_at`) the caller maintains on
writes.

Score semantics: Chroma's `query()` returns a distance, not a
similarity score, and what that distance *means* depends on the
collection's configured space (`l2`, `cosine`, `ip`) at creation time.
This adapter assumes a cosine-space collection and converts via
`score = 1 - distance` to stay consistent with pgvector/Qdrant's score
convention (higher = more similar). A collection created with a
different space will produce scores that aren't directly comparable to
other backends' scores. verify_parity()'s recall@k/overlap checks
still work regardless (they only depend on rank order and id
membership), but mean_score_drift won't mean the same thing across a
metric mismatch.

Typing note: chromadb's own type stubs are narrower than its actual
runtime API. `embeddings`/`where` accept plain Python lists/dicts at
runtime (this is how Chroma's own docs show it), but the stubs are
written against numpy-array and literal-key types. The `# type: ignore`
comments below are for that stub/runtime mismatch, not unverified
assumptions; behavior is confirmed by the integration tests actually
running against a live Chroma instance.
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
