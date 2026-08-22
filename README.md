<p align="center">
  <img src="logo/vecparity_logo.png" alt="VecParity logo" width="320">
</p>

# VecParity

> Live, quality-verified migration between vector databases.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

---

## The Problem

Every team on a managed vector database eventually wants to switch — Pinecone got expensive, you want to self-host, a competitor is faster for your workload. Today that means:

- Copying data over and **hoping** search quality didn't quietly get worse
- A risky, all-at-once cutover, usually with downtime
- No way to prove — to yourself or a client — that the new database still finds the right things

Existing tools stop at "the data arrived." [vector-io/VDF](https://github.com/AI-Northstar-Tech/vector-io) does batch export → import → re-embed across backends, and vendor migration guides (e.g. Qdrant's) only cover moving *into* their own product. **None of them check whether retrieval quality survived the move.**

VecParity does two things nothing else does together: migrates **incrementally, without downtime**, and hands you a **parity report** — recall@k, result overlap, and score drift between old and new — before you cut over.

---

## Installation

```bash
pip install vecparity
```

With backend support:

```bash
pip install "vecparity[pgvector,qdrant,pinecone,milvus,weaviate,chroma]"
pip install "vecparity[all]"
```

---

## Quick Start

```bash
export PGVECTOR_DSN="postgresql://localhost/mydb"
export QDRANT_URL="http://localhost:6333"

# One-shot migration
vecparity migrate --from pgvector://docs --to qdrant://docs

# Live migration: keeps polling for changes until caught up, so your
# app can keep writing to the source the whole time
vecparity migrate --from pgvector://docs --to qdrant://docs --live

# Migrate AND verify retrieval quality survived, gated on a query set
vecparity migrate --from pgvector://docs --to qdrant://docs \
    --live --verify-parity --queries golden_queries.json --min-recall 0.95
```

A failed parity check exits non-zero — wire it into CI or a deploy gate so a bad migration never silently ships.

### Programmatic use

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

---

## What a parity report tells you

For each query, VecParity compares the source's and target's top-k results:

| Metric | Meaning |
|---|---|
| `recall_at_k` | Fraction of the source's top-k ids also returned by the target |
| `jaccard_overlap` | Set overlap of the two top-k result lists |
| `mean_score_drift` | Average similarity-score difference for ids present in both |

`ParityReport.passed` gates on mean recall@k against a threshold you choose — use your own golden query set (real user queries + expected top hits) for a meaningful check, not just random vectors.

---

## Design principles

- **Migration-time only, not a permanent ORM.** VecParity doesn't try to be a universal query API you build your app against forever — that's how abstractions like this end up leaky. Adapters implement five operations (`get`, `upsert`, `delete`, `list_changed_since`, `search`) and nothing more.
- **Incremental by default.** `list_changed_since` + a cursor means re-running a migration only copies what changed, so it's safe to run alongside a live app.
- **Quality, not just presence.** The whole point of this project is the parity report — everything else is plumbing to get there.

---

## Supported backends

| Backend | Status |
|---|---|
| pgvector | ✅ |
| Qdrant | ✅ |
| Pinecone | ✅ |
| Milvus | ✅ |
| Weaviate | ✅ |
| Chroma | ✅ |
| In-memory (testing / reference) | ✅ |

Adding a backend means implementing `VectorDBAdapter` (`vecparity/adapters/base.py`) — see `adapters/memory.py` for the smallest possible reference implementation.

---

## Documentation

Full docs, including per-backend connection details and design rationale, live at [animeshiology.github.io/vecparity](https://animeshiology.github.io/vecparity/).

## Contributing

PRs, issues, and discussions are welcome — especially new backend adapters and real-world golden query sets for testing parity verification against production-shaped data. See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, running tests, and code style.

## License

[MIT](LICENSE)
