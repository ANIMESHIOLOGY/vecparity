"""Qdrant adapter. Requires the `qdrant` extra.

Qdrant only accepts an unsigned integer or a UUID as a point id, so
VectorRecord.id gets mapped to a deterministic UUID5, with the original
id kept in the payload. For Distance.COSINE collections, Qdrant stores
the normalized vector rather than the raw one upserted.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

from vecparity.adapters.base import VectorDBAdapter
from vecparity.types import ScoredMatch, VectorRecord

try:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qm
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "QdrantAdapter requires the 'qdrant' extra: pip install vecparity[qdrant]"
    ) from e

# Fixed namespace for deterministic id -> UUID mapping across runs.
_ID_NAMESPACE = uuid.UUID("6f2b1b7a-6e0a-4f0c-9b0a-6a4a8f9b6b0e")

_ORIGINAL_ID_KEY = "__vecparity_id"


def _point_id(record_id: str) -> str:
    return str(uuid.uuid5(_ID_NAMESPACE, record_id))


class QdrantAdapter(VectorDBAdapter):
    def __init__(
        self,
        client: QdrantClient,
        collection: str,
        updated_at_field: str = "updated_at",
        scroll_batch_size: int = 256,
    ) -> None:
        self.client = client
        self.collection = collection
        self.updated_at_field = updated_at_field
        self.scroll_batch_size = scroll_batch_size

    def get(self, id: str) -> VectorRecord | None:
        points = self.client.retrieve(
            collection_name=self.collection, ids=[_point_id(id)], with_vectors=True
        )
        if not points:
            return None
        return self._to_record(points[0])

    def upsert(self, records: list[VectorRecord]) -> None:
        points = [
            qm.PointStruct(
                id=_point_id(r.id),
                vector=r.vector,
                payload={
                    **r.metadata,
                    self.updated_at_field: r.updated_at,
                    _ORIGINAL_ID_KEY: r.id,
                },
            )
            for r in records
        ]
        self.client.upsert(collection_name=self.collection, points=points)

    def delete(self, ids: list[str]) -> None:
        self.client.delete(
            collection_name=self.collection,
            points_selector=qm.PointIdsList(points=[_point_id(id) for id in ids]),
        )

    def list_changed_since(self, cursor: float | None) -> Iterator[VectorRecord]:
        query_filter = None
        if cursor is not None:
            query_filter = qm.Filter(
                must=[qm.FieldCondition(key=self.updated_at_field, range=qm.Range(gte=cursor))]
            )
        offset = None
        while True:
            points, offset = self.client.scroll(
                collection_name=self.collection,
                scroll_filter=query_filter,
                limit=self.scroll_batch_size,
                offset=offset,
                with_vectors=True,
            )
            for p in points:
                yield self._to_record(p)
            if offset is None:
                break

    def search(self, vector: list[float], top_k: int) -> list[ScoredMatch]:
        # qdrant-client >=1.10 dropped .search() in favor of .query_points().
        response = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            limit=top_k,
            with_payload=True,
        )
        hits = response.points
        return [
            ScoredMatch(
                id=(h.payload or {}).get(_ORIGINAL_ID_KEY, str(h.id)),
                score=h.score,
                metadata={k: v for k, v in (h.payload or {}).items() if k != _ORIGINAL_ID_KEY},
            )
            for h in hits
        ]

    def count(self) -> int:
        return int(self.client.count(collection_name=self.collection).count)

    def _to_record(self, point: qm.Record) -> VectorRecord:
        payload = dict(point.payload or {})
        original_id = payload.pop(_ORIGINAL_ID_KEY, str(point.id))
        updated_at = payload.pop(self.updated_at_field, None)
        return VectorRecord(
            id=original_id,
            vector=list(point.vector or []),
            metadata=payload,
            updated_at=updated_at,
        )
