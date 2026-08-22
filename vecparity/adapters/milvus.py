"""Milvus adapter.

Requires the `milvus` extra: `pip install vecparity[milvus]`.

Assumes a collection already created with (at minimum) a VARCHAR
primary key field, a FLOAT_VECTOR field, a JSON metadata field, and a
DOUBLE updated_at field — e.g.:

    from pymilvus import MilvusClient, DataType
    schema = client.create_schema(auto_id=False)
    schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=256)
    schema.add_field("vector", DataType.FLOAT_VECTOR, dim=768)
    schema.add_field("metadata", DataType.JSON)
    schema.add_field("updated_at", DataType.DOUBLE)
    client.create_collection(name, schema=schema)
    client.create_index(name, field_name="vector", metric_type="COSINE")
    client.load_collection(name)

Field names are configurable via the constructor if yours differ.

Unlike Qdrant/Weaviate, Milvus places no restriction on the primary
key value beyond the declared VARCHAR type — arbitrary strings work
natively, no id-mapping trick needed here.

Milvus requires the collection be explicitly `load()`ed before search
or query works — an unloaded collection returns empty results rather
than an error, which is an easy way to silently think an adapter is
broken when it's actually just an un-loaded collection. This adapter
does not call `load_collection()` itself (it's a slow, whole-collection
operation the caller should control), so make sure the collection is
loaded before using this adapter.

Score semantics: for a COSINE-metric collection, the `distance` field
in Milvus's search results is already the cosine similarity (higher =
better) despite the field's name — Milvus does not need the same
`1 - distance` conversion the other adapters use. Verified against a
real Milvus instance in the integration tests.

Consistency: Milvus defaults to "Bounded" consistency, where a read
can briefly miss a write that just happened (or see a stale prior
value on an overwrite) — confirmed by this adapter's own integration
tests initially failing with exactly that symptom (upsert "succeeds"
but an immediate get()/count() sees nothing or stale data). Every read
here passes `consistency_level="Strong"` to force read-your-writes
visibility, which is what a migration/verification tool needs — a
correctness tool that can't see its own most recent write isn't
trustworthy, and the throughput cost of strong consistency is a
reasonable trade for that here.
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
        filter_expr = f"{self.updated_at_field} > {cursor}" if cursor is not None else ""
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
