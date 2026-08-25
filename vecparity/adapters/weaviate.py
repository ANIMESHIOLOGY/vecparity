"""Weaviate adapter. Requires the `weaviate` extra.

Weaviate requires object ids to be UUIDs, so VectorRecord.id gets
mapped to a deterministic UUID5, with the original id kept in a
property. `near_vector()` returns `distance`, converted to a
similarity score the same way as ChromaAdapter.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from functools import reduce
from typing import Any

from vecparity.adapters.base import VectorDBAdapter
from vecparity.types import ScoredMatch, VectorRecord

try:
    import weaviate.classes as wvc
    from weaviate.collections.collection.sync import Collection
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "WeaviateAdapter requires the 'weaviate' extra: pip install vecparity[weaviate]"
    ) from e

# Fixed namespace for deterministic id -> UUID mapping across runs.
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
            filters = wvc.query.Filter.by_property(self.updated_at_field).greater_or_equal(cursor)
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

    def search(
        self, vector: list[float], top_k: int, filter: dict[str, Any] | None = None
    ) -> list[ScoredMatch]:
        filters = None
        if filter is not None:
            conditions = [wvc.query.Filter.by_property(k).equal(v) for k, v in filter.items()]
            filters = reduce(lambda a, b: a & b, conditions)
        result = self.collection.query.near_vector(
            near_vector=vector,
            filters=filters,
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
