# Changelog

## Unreleased

- **Breaking:** dropped Python 3.9 support, floor raised to 3.10. PEP 604
  `X | None` union syntax is used throughout, including in pydantic models
  and Typer CLI option types — both resolve annotations at *runtime*, not
  just for static type-checkers, and that requires real interpreter
  support for `|` on types (3.10+). Python 3.9 also reached end-of-life
  on 2025-10-31. Caught by CI's Python 3.9 matrix job, which failed on
  `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`
  during pydantic model collection.
- Fixed a real bug in `PineconeAdapter.list_changed_since`: `index.list()`
  yields paginated `ListResponse` objects, each holding a batch of
  `ListItem(id=...)` entries — not bare id strings. The previous code
  would have broken the downstream `fetch()` call against any real
  Pinecone index; never caught locally since Pinecone has no docker-based
  integration test target the way pgvector/Qdrant do.
- Fixed a mypy-only issue in `cli.py`: the Qdrant and Pinecone branches of
  `_load_adapter()` reused one variable name for two different client
  types, which mypy flags even though the branches are mutually
  exclusive at runtime.

## v0.1.0 — Initial release

- Core types (`VectorRecord`, `ScoredMatch`, `QueryCase`)
- `VectorDBAdapter` protocol (get, upsert, delete, list_changed_since, search, count)
- Adapters: in-memory (reference/testing), pgvector, Qdrant, Pinecone
- `SyncEngine` — cursor-based incremental replication (`run_once`, `run_until_caught_up`)
- `verify_parity` — recall@k, Jaccard overlap, and score-drift comparison producing a pass/fail `ParityReport`
- CLI: `vecparity migrate --from ... --to ... [--live] [--verify-parity]`, `vecparity version`
- Unit tests for parity math and sync engine against the in-memory adapter
- Integration tests for pgvector and Qdrant adapters against real Docker containers (`docker-compose.test.yml`), 16/16 passing
- GitHub Actions CI: lint/type-check, unit test matrix (Python 3.9–3.12), integration test job with service containers
- Verified end-to-end against real infrastructure: seeded 200 vectors into pgvector, migrated live to Qdrant via the CLI, parity report confirmed 100% recall@k / overlap, zero score drift

**Real bugs found and fixed during integration testing** (the reason this testing exists):
- pgvector adapter never registered pgvector-python's type adapter, so vector columns round-tripped incorrectly
- pgvector `search()` query params needed an explicit `::vector` cast — Postgres can't infer the type for a bare comparison operand the way it can for an INSERT target column
- Qdrant rejects arbitrary string point IDs (only unsigned int or UUID) — added a deterministic UUID5 mapping, with the caller's original id preserved in the payload
- `qdrant-client` >=1.10 removed `.search()` in favor of `.query_points()`
- Documented (not "fixed" — it's real DB behavior): Qdrant stores cosine-collection vectors normalized, not as-uploaded

**Not yet implemented:** PyPI publish, docs site.
