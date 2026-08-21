# Backend connection reference

The CLI (`vecparity migrate --from ... --to ...`) reads connection details
from environment variables rather than CLI flags, so nothing sensitive
(passwords, API keys) ends up in shell history or process listings.

Programmatic use doesn't go through this at all — construct the adapter
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
`updated_at` — pass `updated_at_field=` to `QdrantAdapter` if yours differs.

## `pinecone://<index>`

| Env var | Required | Notes |
|---|---|---|
| `PINECONE_API_KEY` | yes | |
| `PINECONE_NAMESPACE` | no | Defaults to the default namespace (`""`) |

Pinecone has no native change feed, so `list_changed_since` scrolls every
id via `list()` + `fetch()` and filters on a metadata field (default
`updated_at`) your writes maintain — the slowest adapter to backfill from,
by design it's meant for migrating *out of* Pinecone, not as a long-lived
sync source.

## Adding a new backend

Implement `vecparity.adapters.base.VectorDBAdapter` (five methods: `get`,
`upsert`, `delete`, `list_changed_since`, `search`, plus `count`). See
`vecparity/adapters/memory.py` for the smallest reference implementation,
or `qdrant.py`/`pgvector.py` for a real one. Wire it into `cli.py`'s
`_load_adapter()` and add its env vars to this file.
