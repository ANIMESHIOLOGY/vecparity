"""Milvus adapter. Requires the `milvus` extra.

Assumes a collection with a VARCHAR primary key, a FLOAT_VECTOR field,
a JSON metadata field, and a DOUBLE updated_at field (field names
configurable via the constructor). Must be `load()`ed before use; an
unloaded collection returns empty results instead of an error.

For a COSINE-metric collection, the `distance` field in search results
is already the similarity score, no `1 - distance` conversion needed.

Reads pass `consistency_level="Strong"`: Milvus defaults to "Bounded"
consistency, where a read can briefly miss a write that just happened.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from vecparity.adapters.base import VectorDBAdapter
from vecparity.types import ScoredMatch, VectorRecord

try:
    from pymilvus import MilvusClient
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "MilvusAdapter requires the 'milvus' extra: pip install vecparity[milvus]"
    ) from e


class MilvusAdapter(VectorDBAdapter):
    def __init__(
        self,
        client: MilvusClient,
        collection_name: str,
        id_field: str = "id",
        vector_field: str = "vector",
        metadata_field: str = "metadata",
        updated_at_field: str = "updated_at",
        page_size: int = 256,
    ) -> None:
        self.client = client
        self.collection_name = collection_name
        self.id_field = id_field
        self.vector_field = vector_field
        self.metadata_field = metadata_field
        self.updated_at_field = updated_at_field
        self.page_size = page_size
        self._output_fields = [id_field, vector_field, metadata_field, updated_at_field]

    def get(self, id: str) -> VectorRecord | None:
        rows = self.client.get(
            self.collection_name,
            ids=[id],
            output_fields=self._output_fields,
            consistency_level="Strong",
        )
        if not rows:
            return None
        return self._to_record(rows[0])

    def upsert(self, records: list[VectorRecord]) -> None:
        data = [
            {
                self.id_field: r.id,
                self.vector_field: r.vector,
                self.metadata_field: r.metadata,
                self.updated_at_field: r.updated_at,
            }
            for r in records
        ]
        self.client.upsert(self.collection_name, data=data)

    def delete(self, ids: list[str]) -> None:
        self.client.delete(self.collection_name, ids=ids)

    def list_changed_since(self, cursor: float | None) -> Iterator[VectorRecord]:
        filter_expr = f"{self.updated_at_field} >= {cursor}" if cursor is not None else ""
        offset = 0
        while True:
            rows = self.client.query(
                self.collection_name,
                filter=filter_expr,
                output_fields=self._output_fields,
                limit=self.page_size,
                offset=offset,
                consistency_level="Strong",
            )
            if not rows:
                break
            for row in rows:
                yield self._to_record(row)
            if len(rows) < self.page_size:
                break
            offset += len(rows)

    def search(self, vector: list[float], top_k: int) -> list[ScoredMatch]:
        results = self.client.search(
            self.collection_name,
            data=[vector],
            limit=top_k,
            output_fields=[self.id_field, self.metadata_field],
            consistency_level="Strong",
        )
        matches = []
        for hit in results[0]:
            entity = hit.get("entity", {})
            matches.append(
                ScoredMatch(
                    id=str(entity.get(self.id_field, hit.get("id"))),
                    score=float(hit["distance"]),
                    metadata=dict(entity.get(self.metadata_field, {}) or {}),
                )
            )
        return matches

    def count(self) -> int:
        result = self.client.query(
            self.collection_name,
            filter="",
            output_fields=["count(*)"],
            consistency_level="Strong",
        )
        if result and "count(*)" in result[0]:
            return int(result[0]["count(*)"])
        # Fallback: some pymilvus versions need the expression form instead.
        stats = self.client.get_collection_stats(self.collection_name)
        return int(stats.get("row_count", 0))

    def _to_record(self, row: dict[str, Any]) -> VectorRecord:
        metadata = dict(row.get(self.metadata_field) or {})
        return VectorRecord(
            id=str(row[self.id_field]),
            vector=[float(x) for x in row[self.vector_field]],
            metadata=metadata,
            updated_at=row.get(self.updated_at_field),
        )
