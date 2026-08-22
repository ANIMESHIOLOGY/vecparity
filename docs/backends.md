# Backend connection reference

The CLI (`vecparity migrate --from ... --to ...`) reads connection details
from environment variables rather than CLI flags, so nothing sensitive
(passwords, API keys) ends up in shell history or process listings.

Programmatic use doesn't go through this at all: construct the adapter
class directly with your own client/connection object.

## `pgvector://<table>`

| Env var | Required | Notes |
|---|---|---|
| `PGVECTOR_DSN` | yes | Full connection string, e.g. `postgresql://user:pass@host:5432/db` |

Assumes a table shaped like:

```sql
CREATE TABLE <table> (
    id TEXT PRIMARY KEY,
    embedding VECTOR(<dim>),
    metadata JSONB DEFAULT '{}',
    updated_at DOUBLE PRECISION
);
```

Use `PgVectorAdapter(conn, table, id_col=..., vector_col=..., metadata_col=..., updated_at_col=...)` directly if your column names differ.

## `qdrant://<collection>`

| Env var | Required | Notes |
|---|---|---|
| `QDRANT_URL` | no | Defaults to `http://localhost:6333` |
| `QDRANT_API_KEY` | no | Needed for Qdrant Cloud |

Change tracking (`list_changed_since`) filters on a payload field, default
`updated_at`. Pass `updated_at_field=` to `QdrantAdapter` if yours differs.

## `pinecone://<index>`

| Env var | Required | Notes |
|---|---|---|
| `PINECONE_API_KEY` | yes | |
| `PINECONE_NAMESPACE` | no | Defaults to the default namespace (`""`) |

Pinecone has no native change feed, so `list_changed_since` scrolls every
id via `list()` + `fetch()` and filters on a metadata field (default
`updated_at`) your writes maintain. It's the slowest adapter to backfill
from, since by design it's meant for migrating *out of* Pinecone, not as
a long-lived sync source.

## `milvus://<collection>`

| Env var | Required | Notes |
|---|---|---|
| `MILVUS_URI` | no | Defaults to `http://localhost:19530` |

Assumes a collection already created with a VARCHAR primary key, a
FLOAT_VECTOR field, a JSON metadata field, and a DOUBLE `updated_at`
field: see `MilvusAdapter`'s module docstring for the exact schema and
index setup. The collection must be `load()`ed before use; an unloaded
collection returns empty results rather than an error.

Every read passes `consistency_level="Strong"`. Milvus defaults to
"Bounded" consistency, where a read can briefly miss a write that just
happened. This was caught by the adapter's own integration tests
initially failing with exactly that symptom (upsert "succeeds" but an
immediate `get()`/`count()` sees nothing or a stale prior value).

## `weaviate://<collection>`

| Env var | Required | Notes |
|---|---|---|
| `WEAVIATE_HOST` | no | Defaults to `localhost` |
| `WEAVIATE_PORT` | no | Defaults to `8080` |
| `WEAVIATE_GRPC_PORT` | no | Defaults to `50051` |

Like Qdrant, Weaviate only accepts UUID object ids. `WeaviateAdapter`
maps arbitrary string ids to a deterministic UUID5, same as
`QdrantAdapter`. Change tracking filters on a property (default
`updated_at`) your writes maintain.

## `chroma://<collection>`

| Env var | Required | Notes |
|---|---|---|
| `CHROMA_HOST` | no | Defaults to `localhost` |
| `CHROMA_PORT` | no | Defaults to `8000` |

Simplest adapter: Chroma accepts arbitrary string ids natively and has
a native `upsert()`, so there's no id-mapping trick needed. Assumes the
collection was created with cosine distance (`metadata={"hnsw:space":
"cosine"}`) for the adapter's `score = 1 - distance` conversion to be
directly comparable to the other backends' scores.

## Adding a new backend

Implement `vecparity.adapters.base.VectorDBAdapter` (five methods: `get`,
`upsert`, `delete`, `list_changed_since`, `search`, plus `count`). See
`vecparity/adapters/memory.py` for the smallest reference implementation,
or `qdrant.py`/`pgvector.py` for a real one. Wire it into `cli.py`'s
`_load_adapter()` and add its env vars to this file.
