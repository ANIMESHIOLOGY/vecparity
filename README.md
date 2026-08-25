<p align="center">
  <img src="logo/vecparity_logo.png" alt="VecParity logo" width="320">
</p>

<h1 align="center">VecParity</h1>

<p align="center"><strong>Live, quality-verified migration between vector databases.</strong></p>

<p align="center">
  <a href="https://pypi.org/project/vecparity/"><img src="https://img.shields.io/pypi/v/vecparity.svg?color=005bfd" alt="PyPI version"></a>
  <a href="https://pypi.org/project/vecparity/"><img src="https://img.shields.io/pypi/pyversions/vecparity.svg?color=8000d6" alt="Python versions"></a>
  <a href="https://github.com/ANIMESHIOLOGY/vecparity/actions/workflows/ci.yml"><img src="https://github.com/ANIMESHIOLOGY/vecparity/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
</p>

<p align="center">
  <a href="https://animeshiology.github.io/vecparity/">Docs</a> ·
  <a href="#installation">Installation</a> ·
  <a href="#quick-start">Quick Start</a> ·
  <a href="#supported-backends">Backends</a> ·
  <a href="CONTRIBUTING.md">Contributing</a>
</p>

---

## The Problem

Every team on a managed vector database eventually wants to switch: Pinecone got expensive, you want to self-host, a competitor is faster for your workload. Today that means:

- Copying data over and **hoping** search quality didn't quietly get worse
- A risky, all-at-once cutover, usually with downtime
- No way to prove, to yourself or a client, that the new database still finds the right things

| | Confirms data arrived | Confirms search quality survived | Zero downtime |
|---|:---:|:---:|:---:|
| [vector-io/VDF](https://github.com/AI-Northstar-Tech/vector-io) | ✅ | ❌ | ❌ |
| Vendor migration guides | ✅ | ❌ | ❌ |
| **VecParity** | ✅ | ✅ | ✅ |

VecParity migrates **incrementally, without downtime**, and hands you a **parity report** (recall@k, result overlap, and score drift between old and new) before you cut over.

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

# Check the two sides are compatible before touching any data:
# vector dimension, metadata field types, whether the target is already populated
vecparity plan --from pgvector://docs --to qdrant://docs

# Pre-flight: connectivity to both sides, and a real write probe against the target
vecparity validate --from pgvector://docs --to qdrant://docs

# One-shot migration
vecparity migrate run --from pgvector://docs --to qdrant://docs

# Live migration: keeps polling for changes until caught up, so your
# app can keep writing to the source the whole time
vecparity migrate run --from pgvector://docs --to qdrant://docs --live

# Migrate AND verify retrieval quality survived, gated on a query set
vecparity migrate run --from pgvector://docs --to qdrant://docs \
    --live --verify-parity --queries golden_queries.json --min-recall 0.95
```

A migration in progress checkpoints its cursor to `~/.vecparity/checkpoints.db`, so a crashed or interrupted `--live` run resumes from where it left off instead of starting over. `vecparity checkpoint show`/`clear` inspect or discard that state.

A failed parity or compatibility check exits non-zero, so any of these can wire into CI or a deploy gate to stop a bad migration from silently shipping.

### Cutover Workflow

Once a live migration is caught up and verified, there's a defined, visible path to actually cutting over, not just a `migrate run` you either trust blindly or don't run at all:

```bash
# Check on a migration from another terminal while --live is running
vecparity migrate status --from pgvector://docs --to qdrant://docs

# Request a running --live migration to stop cleanly at its next poll
vecparity migrate pause --from pgvector://docs --to qdrant://docs
# ...re-run `migrate run` (no --fresh) later to resume from the checkpoint

# Mark a migration cancelled; a future `migrate run` refuses to resume
# it without --fresh
vecparity migrate cancel --from pgvector://docs --to qdrant://docs

# Final sync pass + final parity check; only marks the migration cut
# over if it passes. --report-json/--report-html write a combined
# migration + parity report, a self-contained HTML page or JSON.
vecparity cutover --from pgvector://docs --to qdrant://docs \
    --queries golden_queries.json --min-recall 0.95 \
    --report-html cutover_report.html

# Record that a cut-over migration was rolled back
vecparity rollback --from pgvector://docs --to qdrant://docs
```

Worth being precise about what this does and doesn't do: vecparity has no way to redirect your application's traffic, and `rollback` doesn't sync data back to the source, it isn't a two-way replication tool. `cutover`/`rollback` track migration state and give you evidence (a fresh final parity check) for a decision you still make and act on yourself.

### Benchmarking

```bash
vecparity benchmark --from memory://bench-source --to qdrant://mycollection \
    --num-records 200000 --dimension 128
```

Seeds synthetic vectors and times a real sync, reporting throughput, batch count, and peak memory. This measures whatever machine and backend you point it at, not a universal number; see [Benchmarking](https://animeshiology.github.io/vecparity/benchmarking/) for methodology and one real data point.

### Programmatic Use

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
    queries=[
        QueryCase(query_id="doc-123", top_k=10, label="spot check"),
        # filter is replayed on both sides, so parity is checked on the
        # same filtered path a real query would take
        QueryCase(query_vector=[...], top_k=10, filter={"tenant_id": "acme"}),
    ],
    min_recall_at_k=0.9,
)
print(report.summary())
assert report.passed
```

---

## What a Parity Report Tells You

For each query, VecParity compares the source's and target's top-k results:

| Metric | Meaning |
|---|---|
| `recall_at_k` | Fraction of the source's top-k ids also returned by the target |
| `jaccard_overlap` | Set overlap of the two top-k result lists |
| `mean_score_drift` | Average similarity-score difference for ids present in both |

The report also aggregates across the whole query set: `mean_recall_at_k`, `p50_recall`, `p95_recall`, `min_recall`, and `queries_below_threshold_pct`, so one badly-served query can't hide inside a passing average. `ParityReport.passed` gates on the mean recall@k against a threshold you choose, and optionally on `min_per_query_recall`, a floor every individual query must also clear. A query can carry a `filter` (equality-only metadata filter), replayed against both sides, so the check exercises the same filtered path a real query would take, not just plain unfiltered similarity.

Use your own golden query set (real user queries plus expected top hits) for a meaningful check, not just random vectors.

---

## Design Principles

- **Migration-time only, not a permanent ORM.** VecParity doesn't try to be a universal query API you build your app against forever; that's how abstractions like this end up leaky. Adapters implement six operations (`get`, `upsert`, `delete`, `list_changed_since`, `search`, `count`), plus one optional one for delete tracking (`list_deleted_since`), and nothing more.
- **Incremental by default.** `list_changed_since` plus a cursor means re-running a migration only copies what changed, so it's safe to run alongside a live app.
- **Quality, not just presence.** The whole point of this project is the parity report; everything else is plumbing to get there.
- **Narrow on purpose, even under pressure to grow.** `search()`'s `filter` is equality-only, not a cross-backend query DSL; `cutover`/`rollback` track state and run a real verification pass, they don't fake application-traffic control or reverse data sync, which vecparity has no way to actually do. Saying no to scope here is deliberate, not an oversight.

---

## Supported Backends

| Backend | Status |
|---|:---:|
| pgvector | ✅ |
| Qdrant | ✅ |
| Pinecone | ✅ |
| Milvus | ✅ |
| Weaviate | ✅ |
| Chroma | ✅ |
| In-memory (testing / reference) | ✅ |

Adding a backend means implementing `VectorDBAdapter` (`vecparity/adapters/base.py`); see `adapters/memory.py` for the smallest possible reference implementation.

---

## Documentation

Full docs, including per-backend connection details and design rationale, live at [animeshiology.github.io/vecparity](https://animeshiology.github.io/vecparity/).

## Contributing

PRs, issues, and discussions are welcome, especially new backend adapters and real-world golden query sets for testing parity verification against production-shaped data. See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, running tests, and code style.

## License

[MIT](LICENSE)
