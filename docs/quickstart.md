# Quick Start

## CLI

```bash
export PGVECTOR_DSN="postgresql://localhost/mydb"
export QDRANT_URL="http://localhost:6333"

# One-shot migration
vecparity migrate run --from pgvector://docs --to qdrant://docs

# Live migration: keeps polling for changes until caught up, so your
# app can keep writing to the source the whole time
vecparity migrate run --from pgvector://docs --to qdrant://docs --live

# Migrate AND verify retrieval quality survived, gated on a query set
vecparity migrate run --from pgvector://docs --to qdrant://docs \
    --live --verify-parity --queries golden_queries.json --min-recall 0.95
```

A failed parity check exits non-zero, so it can wire into CI or a
deploy gate to stop a bad migration from silently shipping.

Once a live migration is caught up and verified, `vecparity migrate status/pause/cancel` and `vecparity cutover`/`rollback` give a defined path to actually cutting over; see [cutover.md](cutover.md).

`golden_queries.json` is a list of query cases:

```json
[
  {"query_id": "doc-5", "top_k": 5, "label": "doc-5 neighbors"},
  {"query_vector": [0.1, 0.2, 0.3, 0.4], "top_k": 10, "label": "explicit vector"}
]
```

Either `query_id` (searches using an existing record's vector from the
source) or `query_vector` (an explicit vector) works. Use real user
queries and their expected top hits for a meaningful check; random
vectors won't tell you much about actual retrieval quality.

## Python

```python
from vecparity.adapters.pgvector import PgVectorAdapter
from vecparity.adapters.qdrant import QdrantAdapter
from vecparity.sync.engine import SyncEngine
from vecparity.verify.parity import verify_parity
from vecparity.types import QueryCase

source = PgVectorAdapter(conn=pg_conn, table="docs")
target = QdrantAdapter(client=qdrant_client, collection="docs")

SyncEngine(source, target).run_until_caught_up()

report = verify_parity(
    source, target,
    queries=[QueryCase(query_id="doc-123", top_k=10, label="spot check")],
    min_recall_at_k=0.9,
)
print(report.summary())
assert report.passed
```

## Reading a parity report

| Metric | Meaning |
|---|---|
| `recall_at_k` | Fraction of the source's top-k ids also returned by the target |
| `jaccard_overlap` | Set overlap of the two top-k result lists |
| `mean_score_drift` | Average similarity-score difference for ids present in both |

`ParityReport.passed` gates on mean recall@k against the threshold you
pass to `verify_parity()` (or `--min-recall` on the CLI).
