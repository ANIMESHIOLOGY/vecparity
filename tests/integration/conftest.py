"""Fixtures for adapter integration tests.

These connect to real backends (see ../../docker-compose.test.yml) rather
than mocking anything. The whole point of these tests is to catch the
class of bug unit tests against the in-memory adapter can't: wrong SQL,
missing type adapters, wrong client API calls.

Every fixture skips (not fails) if its backend isn't reachable, so
`pytest` stays green without docker running locally; CI starts the
same docker-compose.test.yml stack before running these.
"""

from __future__ import annotations

import os

import pytest

PGVECTOR_TEST_DSN = os.environ.get(
    "VECPARITY_TEST_PGVECTOR_DSN",
    "postgresql://postgres:postgres@localhost:55432/vecparity_test",
)
QDRANT_TEST_URL = os.environ.get("VECPARITY_TEST_QDRANT_URL", "http://localhost:56333")
WEAVIATE_TEST_HOST = os.environ.get("VECPARITY_TEST_WEAVIATE_HOST", "localhost")
WEAVIATE_TEST_PORT = int(os.environ.get("VECPARITY_TEST_WEAVIATE_PORT", "58080"))
WEAVIATE_TEST_GRPC_PORT = int(os.environ.get("VECPARITY_TEST_WEAVIATE_GRPC_PORT", "58051"))
CHROMA_TEST_HOST = os.environ.get("VECPARITY_TEST_CHROMA_HOST", "localhost")
CHROMA_TEST_PORT = int(os.environ.get("VECPARITY_TEST_CHROMA_PORT", "58000"))
MILVUS_TEST_URI = os.environ.get("VECPARITY_TEST_MILVUS_URI", "http://localhost:59530")


@pytest.fixture
def pg_conn():
    psycopg = pytest.importorskip("psycopg")
    try:
        conn = psycopg.connect(PGVECTOR_TEST_DSN, connect_timeout=2)
    except Exception as e:  # noqa: BLE001 - deliberately broad, this is a skip condition
        pytest.skip(f"pgvector not reachable at {PGVECTOR_TEST_DSN}: {e}")
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def qdrant_client():
    qc = pytest.importorskip("qdrant_client")
    client = qc.QdrantClient(url=QDRANT_TEST_URL, timeout=2)
    try:
        client.get_collections()
    except Exception as e:  # noqa: BLE001 - deliberately broad, this is a skip condition
        pytest.skip(f"Qdrant not reachable at {QDRANT_TEST_URL}: {e}")
    yield client


@pytest.fixture
def weaviate_client():
    weaviate = pytest.importorskip("weaviate")
    try:
        client = weaviate.connect_to_local(
            host=WEAVIATE_TEST_HOST, port=WEAVIATE_TEST_PORT, grpc_port=WEAVIATE_TEST_GRPC_PORT
        )
        if not client.is_ready():
            raise RuntimeError("not ready")
    except Exception as e:  # noqa: BLE001 - deliberately broad, this is a skip condition
        pytest.skip(f"Weaviate not reachable at {WEAVIATE_TEST_HOST}:{WEAVIATE_TEST_PORT}: {e}")
    yield client
    client.close()


@pytest.fixture
def chroma_client():
    chromadb = pytest.importorskip("chromadb")
    client = chromadb.HttpClient(host=CHROMA_TEST_HOST, port=CHROMA_TEST_PORT)
    try:
        client.heartbeat()
    except Exception as e:  # noqa: BLE001 - deliberately broad, this is a skip condition
        pytest.skip(f"Chroma not reachable at {CHROMA_TEST_HOST}:{CHROMA_TEST_PORT}: {e}")
    yield client


@pytest.fixture
def milvus_client():
    pymilvus = pytest.importorskip("pymilvus")
    client = pymilvus.MilvusClient(uri=MILVUS_TEST_URI, timeout=2)
    try:
        client.list_collections()
    except Exception as e:  # noqa: BLE001 - deliberately broad, this is a skip condition
        pytest.skip(f"Milvus not reachable at {MILVUS_TEST_URI}: {e}")
    yield client
