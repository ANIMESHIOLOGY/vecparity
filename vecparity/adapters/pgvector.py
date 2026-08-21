"""pgvector adapter.

Requires the `pgvector` extra: `pip install vecparity[pgvector]`.

Assumes a table shaped like:

    CREATE TABLE {table} (
        id TEXT PRIMARY KEY,
        embedding VECTOR({dim}),
        metadata JSONB DEFAULT '{}',
        updated_at DOUBLE PRECISION
    );

Point `id_col` / `vector_col` / `metadata_col` / `updated_at_col` at your
own column names if they differ.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

from vecparity.adapters.base import VectorDBAdapter
from vecparity.types import ScoredMatch, VectorRecord

try:
    import psycopg
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "PgVectorAdapter requires the 'pgvector' extra: pip install vecparity[pgvector]"
    ) from e


class PgVectorAdapter(VectorDBAdapter):
    def __init__(
        self,
        conn: psycopg.Connection,
        table: str,
        id_col: str = "id",
        vector_col: str = "embedding",
        metadata_col: str = "metadata",
        updated_at_col: str = "updated_at",
        distance_op: str = "<=>",  # cosine; use "<->" for L2, "<#>" for inner product
    ) -> None:
        self.conn = conn
        self.table = table
        self.id_col = id_col
        self.vector_col = vector_col
        self.metadata_col = metadata_col
        self.updated_at_col = updated_at_col
        self.distance_op = distance_op

        # Without this, psycopg has no idea how to adapt a Python list to
        # the `vector` column type (or back) and inserts/searches fail.
        from pgvector.psycopg import register_vector

        register_vector(conn)

    def get(self, id: str) -> VectorRecord | None:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {self.id_col}, {self.vector_col}, {self.metadata_col}, "
                f"{self.updated_at_col} FROM {self.table} WHERE {self.id_col} = %s",
                (id,),
            )
            row = cur.fetchone()
        return self._to_record(row) if row else None

    def upsert(self, records: list[VectorRecord]) -> None:
        now = time.time()
        with self.conn.cursor() as cur:
            for r in records:
                cur.execute(
                    f"""
                    INSERT INTO {self.table}
                        ({self.id_col}, {self.vector_col}, {self.metadata_col}, {self.updated_at_col})
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT ({self.id_col}) DO UPDATE SET
                        {self.vector_col} = EXCLUDED.{self.vector_col},
                        {self.metadata_col} = EXCLUDED.{self.metadata_col},
                        {self.updated_at_col} = EXCLUDED.{self.updated_at_col}
                    """,
                    (r.id, r.vector, json.dumps(r.metadata), r.updated_at or now),
                )
        self.conn.commit()

    def delete(self, ids: list[str]) -> None:
        with self.conn.cursor() as cur:
            cur.execute(f"DELETE FROM {self.table} WHERE {self.id_col} = ANY(%s)", (ids,))
        self.conn.commit()

    def list_changed_since(self, cursor: float | None) -> Iterator[VectorRecord]:
        with self.conn.cursor(name="vecparity_scroll") as cur:  # server-side cursor
            if cursor is None:
                cur.execute(
                    f"SELECT {self.id_col}, {self.vector_col}, {self.metadata_col}, "
                    f"{self.updated_at_col} FROM {self.table} ORDER BY {self.id_col}"
                )
            else:
                cur.execute(
                    f"SELECT {self.id_col}, {self.vector_col}, {self.metadata_col}, "
                    f"{self.updated_at_col} FROM {self.table} "
                    f"WHERE {self.updated_at_col} > %s ORDER BY {self.updated_at_col}",
                    (cursor,),
                )
            for row in cur:
                yield self._to_record(row)

    def search(self, vector: list[float], top_k: int) -> list[ScoredMatch]:
        # register_vector() adapts a *column's* type from context (e.g. the
        # target column in an INSERT), but a bare query parameter compared
        # via <=> has no such context, so Postgres infers it as
        # `double precision[]` and the operator lookup fails — needs an
        # explicit ::vector cast here.
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {self.id_col}, {self.metadata_col},
                       1 - ({self.vector_col} {self.distance_op} %s::vector) AS score
                FROM {self.table}
                ORDER BY {self.vector_col} {self.distance_op} %s::vector
                LIMIT %s
                """,
                (vector, vector, top_k),
            )
            rows = cur.fetchall()
        return [ScoredMatch(id=row[0], score=float(row[2]), metadata=row[1] or {}) for row in rows]

    def count(self) -> int:
        with self.conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {self.table}")
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def _to_record(self, row: tuple[Any, ...]) -> VectorRecord:
        id, vector, metadata, updated_at = row
        # pgvector-python returns its own Vector wrapper (not directly
        # iterable) around a numpy array; Pydantic's list[float] also needs
        # plain floats, not numpy scalars, to validate without strict-mode
        # errors — hence the explicit to_list() + float() conversion.
        return VectorRecord(
            id=id,
            vector=[float(x) for x in vector.to_list()],
            metadata=metadata or {},
            updated_at=updated_at,
        )
