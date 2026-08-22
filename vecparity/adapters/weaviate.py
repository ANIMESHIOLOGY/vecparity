"""Weaviate adapter.

Requires the `weaviate` extra: `pip install vecparity[weaviate]`.

Object IDs: like Qdrant, Weaviate requires every object id to be a
UUID — arbitrary strings are rejected. Same fix as QdrantAdapter: map
VectorRecord.id to a deterministic UUID5 and keep the caller's original
id in a property, so the public interface still accepts/returns
arbitrary strings.

Change tracking: no native change feed, so `list_changed_since` filters
on a property (default `updated_at`) the caller maintains on writes,
paginating via `fetch_objects(after=...)` cursor.

Upsert: the v4 client's `data.insert()` fails if the id already
exists and `data.replace()` fails if it doesn't — there's no single
upsert call, so this adapter checks `data.exists()` first.

Score semantics: `near_vector()` returns `distance`, not similarity —
same `score = 1 - distance` conversion as ChromaAdapter, assuming a
cosine-distance collection.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

from vecparity.adapters.base import VectorDBAdapter
from vecparity.types import ScoredMatch, VectorRecord

try:
    import weaviate.classes as wvc
    from weaviate.collections.collection.sync import Collection
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "WeaviateAdapter requires the 'weaviate' extra: pip install vecparity[weaviate]"
    ) from e

# Fixed namespace so the same VectorRecord.id always maps to the same
# Weaviate object UUID across processes/runs.
_ID_NAMESPACE = uuid.UUID("3c9a5b7e-2f1d-4a6c-8e0b-7d5f9a1c3b2e")

_ORIGINAL_ID_KEY = "_vecparity_id"


def _object_id(record_id: str) -> uuid.UUID:
    return uuid.uuid5(_ID_NAMESPACE, record_id)


class WeaviateAdapter(VectorDBAdapter):
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
        obj = self.collection.query.fetch_object_by_id(_object_id(id), include_vector=True)
        if obj is None:
            return None
        return self._to_record(obj)

    def upsert(self, records: list[VectorRecord]) -> None:
        for r in records:
            oid = _object_id(r.id)
            properties = {
                **r.metadata,
                self.updated_at_field: r.updated_at,
                _ORIGINAL_ID_KEY: r.id,
            }
            if self.collection.data.exists(oid):
                self.collection.data.replace(uuid=oid, properties=properties, vector=r.vector)
            else:
                self.collection.data.insert(uuid=oid, properties=properties, vector=r.vector)

    def delete(self, ids: list[str]) -> None:
        for id in ids:
            self.collection.data.delete_by_id(_object_id(id))

    def list_changed_since(self, cursor: float | None) -> Iterator[VectorRecord]:
        filters = None
        if cursor is not None:
            filters = wvc.query.Filter.by_property(self.updated_at_field).greater_than(cursor)
        after = None
        while True:
            result = self.collection.query.fetch_objects(
                filters=filters,
                limit=self.page_size,
                after=after,
                include_vector=True,
            )
            objects = result.objects
            if not objects:
                break
            for obj in objects:
                yield self._to_record(obj)
            if len(objects) < self.page_size:
                break
            after = objects[-1].uuid

    def search(self, vector: list[float], top_k: int) -> list[ScoredMatch]:
        result = self.collection.query.near_vector(
            near_vector=vector,
            limit=top_k,
            return_metadata=wvc.query.MetadataQuery(distance=True),
        )
        matches = []
        for obj in result.objects:
            props = dict(obj.properties)
            original_id = props.pop(_ORIGINAL_ID_KEY, str(obj.uuid))
            props.pop(self.updated_at_field, None)
            distance = (
                obj.metadata.distance if obj.metadata and obj.metadata.distance is not None else 0.0
            )
            matches.append(ScoredMatch(id=original_id, score=1.0 - distance, metadata=props))
        return matches

    def count(self) -> int:
        result = self.collection.aggregate.over_all(total_count=True)
        return int(result.total_count or 0)

    def _to_record(self, obj: object) -> VectorRecord:
        properties = dict(obj.properties)  # type: ignore[attr-defined]
        original_id = properties.pop(_ORIGINAL_ID_KEY, str(obj.uuid))  # type: ignore[attr-defined]
        updated_at = properties.pop(self.updated_at_field, None)
        vector = obj.vector.get("default", []) if obj.vector else []  # type: ignore[attr-defined]
        return VectorRecord(
            id=original_id,
            vector=[float(x) for x in vector],
            metadata=properties,
            updated_at=updated_at,
        )
