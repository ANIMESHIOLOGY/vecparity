"""Fixtures for adapter integration tests.

These connect to real backends (see ../../docker-compose.test.yml) rather
than mocking anything — the whole point of these tests is to catch the
class of bug unit tests against the in-memory adapter can't: wrong SQL,
missing type adapters, wrong client API calls.

Every fixture skips (not fails) if its backend isn't reachable, so
`pytest` stays green without docker running locally; CI starts the
backends as service containers before running these.
"""

from __future__ import annotations

import os

import pytest

PGVECTOR_TEST_DSN = os.environ.get(
    "VECPARITY_TEST_PGVECTOR_DSN",
    "postgresql://postgres:postgres@localhost:55432/vecparity_test",
)
QDRANT_TEST_URL = os.environ.get("VECPARITY_TEST_QDRANT_URL", "http://localhost:56333")


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
