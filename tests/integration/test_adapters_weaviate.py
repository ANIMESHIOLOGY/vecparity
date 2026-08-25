"""Integration tests for WeaviateAdapter against a real Weaviate instance.

Run: docker compose -f docker-compose.test.yml up -d && pytest -m integration
"""

from __future__ import annotations

import pytest

from vecparity.adapters.weaviate import WeaviateAdapter
from vecparity.types import VectorRecord

pytestmark = pytest.mark.integration

COLLECTION = "VecparityTestDocs"  # Weaviate collection names must be capitalized


@pytest.fixture
def adapter(weaviate_client):
    import weaviate.classes as wvc

    if weaviate_client.collections.exists(COLLECTION):
        weaviate_client.collections.delete(COLLECTION)
    weaviate_client.collections.create(
        COLLECTION,
        vector_config=wvc.config.Configure.Vectors.self_provided(
            vector_index_config=wvc.config.Configure.VectorIndex.hnsw(
                distance_metric=wvc.config.VectorDistances.COSINE
            )
        ),
    )
    yield WeaviateAdapter(collection=weaviate_client.collections.get(COLLECTION))
    weaviate_client.collections.delete(COLLECTION)


def test_upsert_and_get_roundtrip(adapter):
    adapter.upsert([VectorRecord(id="a", vector=[1.0, 2.0, 3.0], metadata={"k": "v"})])

    fetched = adapter.get("a")

    assert fetched is not None
    assert fetched.id == "a"
    assert [round(x, 4) for x in fetched.vector] == [1.0, 2.0, 3.0]
    assert fetched.metadata == {"k": "v"}


def test_get_missing_id_returns_none(adapter):
    assert adapter.get("does-not-exist") is None


def test_upsert_is_idempotent_overwrite(adapter):
    adapter.upsert([VectorRecord(id="a", vector=[1.0, 0.0, 0.0], metadata={"v": 1})])
    adapter.upsert([VectorRecord(id="a", vector=[0.0, 1.0, 0.0], metadata={"v": 2})])

    fetched = adapter.get("a")
    assert fetched.metadata == {"v": 2}
    assert adapter.count() == 1


def test_search_returns_nearest_neighbor_first(adapter):
    adapter.upsert(
        [
            VectorRecord(id="near", vector=[1.0, 0.0, 0.0]),
            VectorRecord(id="far", vector=[-1.0, 0.0, 0.0]),
        ]
    )

    hits = adapter.search([1.0, 0.0, 0.0], top_k=2)

    assert hits[0].id == "near"
    assert hits[0].score > hits[1].score


def test_search_with_filter_excludes_non_matching(adapter):
    # Well-separated (~46 deg) so an approximate index can't blur the
    # ranking the way two near-identical vectors could.
    adapter.upsert(
        [
            VectorRecord(id="keep", vector=[1.0, 0.0, 0.0], metadata={"tag": "keep"}),
            VectorRecord(id="drop", vector=[0.7, 0.714, 0.0], metadata={"tag": "drop"}),
        ]
    )

    unfiltered = adapter.search([0.7, 0.714, 0.0], top_k=1)
    assert unfiltered[0].id == "drop"

    filtered = adapter.search([0.7, 0.714, 0.0], top_k=1, filter={"tag": "keep"})
    assert filtered[0].id == "keep"


def test_delete_removes_record(adapter):
    adapter.upsert([VectorRecord(id="x", vector=[0.0, 0.0, 1.0])])
    assert adapter.get("x") is not None

    adapter.delete(["x"])

    assert adapter.get("x") is None


def test_list_changed_since_only_returns_newer_records(adapter):
    adapter.upsert([VectorRecord(id="old", vector=[0.0, 0.0, 0.0], updated_at=100.0)])
    adapter.upsert([VectorRecord(id="new", vector=[1.0, 1.0, 1.0], updated_at=200.0)])

    changed = list(adapter.list_changed_since(150.0))

    assert {r.id for r in changed} == {"new"}


def test_list_changed_since_none_returns_everything(adapter):
    adapter.upsert([VectorRecord(id=f"d{i}", vector=[float(i), 0.0, 0.0]) for i in range(5)])

    changed = list(adapter.list_changed_since(None))

    assert {r.id for r in changed} == {f"d{i}" for i in range(5)}


def test_count(adapter):
    adapter.upsert([VectorRecord(id=f"d{i}", vector=[float(i), 0.0, 0.0]) for i in range(5)])

    assert adapter.count() == 5
