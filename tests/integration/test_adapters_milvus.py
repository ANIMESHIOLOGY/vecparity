"""Integration tests for MilvusAdapter against a real Milvus instance.

Run: docker compose -f docker-compose.test.yml up -d && pytest -m integration

Milvus takes noticeably longer to become healthy than the other
backends (it depends on separate etcd and minio containers coming up
first). The docker-compose healthcheck accounts for this with a longer
start_period and more retries.
"""

from __future__ import annotations

import pytest

from vecparity.adapters.milvus import MilvusAdapter
from vecparity.types import VectorRecord

pytestmark = pytest.mark.integration

COLLECTION = "vecparity_test_docs"


@pytest.fixture
def adapter(milvus_client):
    from pymilvus import DataType

    if milvus_client.has_collection(COLLECTION):
        milvus_client.drop_collection(COLLECTION)

    schema = milvus_client.create_schema(auto_id=False)
    schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=256)
    schema.add_field("vector", DataType.FLOAT_VECTOR, dim=3)
    schema.add_field("metadata", DataType.JSON)
    schema.add_field("updated_at", DataType.DOUBLE, nullable=True)
    milvus_client.create_collection(COLLECTION, schema=schema)
    milvus_client.create_index(
        COLLECTION,
        index_params=milvus_client.prepare_index_params(
            field_name="vector", index_type="AUTOINDEX", metric_type="COSINE"
        ),
    )
    milvus_client.load_collection(COLLECTION)

    yield MilvusAdapter(client=milvus_client, collection_name=COLLECTION)
    milvus_client.drop_collection(COLLECTION)


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
