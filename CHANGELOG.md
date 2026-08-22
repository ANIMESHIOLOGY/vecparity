# Changelog

## v0.1.0 — Initial release

- Core types (`VectorRecord`, `ScoredMatch`, `QueryCase`)
- `VectorDBAdapter` protocol (get, upsert, delete, list_changed_since, search, count)
- Adapters: in-memory (reference/testing), pgvector, Qdrant, Pinecone
- `SyncEngine` — cursor-based incremental replication (`run_once`, `run_until_caught_up`)
- `verify_parity` — recall@k, Jaccard overlap, and score-drift comparison producing a pass/fail `ParityReport`
- CLI: `vecparity migrate --from ... --to ... [--live] [--verify-parity]`, `vecparity version`
- Unit tests for parity math and sync engine against the in-memory adapter
- Integration tests for pgvector and Qdrant adapters against real Docker containers (`docker-compose.test.yml`), 16/16 passing
- GitHub Actions CI: lint/type-check, unit test matrix (Python 3.10–3.13), integration test job with service containers
- Verified end-to-end against real infrastructure: seeded 200 vectors into pgvector, migrated live to Qdrant via the CLI, parity report confirmed 100% recall@k / overlap, zero score drift
- Requires Python >=3.10: PEP 604 `X | None` union syntax is used throughout, including in pydantic models and Typer CLI option types — both resolve annotations at runtime, which needs real interpreter support for `|` on types (3.10+). Python 3.9 also reached end-of-life on 2025-10-31.
- `CONTRIBUTING.md`, GitHub issue templates, and an mkdocs documentation site (`mkdocs.yml`, `docs/`, deployed via `.github/workflows/docs.yml`)

**Real bugs found and fixed during development** (mostly via integration testing against real backends, one via CI's Python 3.9 matrix job before that version was dropped):
- pgvector adapter never registered pgvector-python's type adapter, so vector columns round-tripped incorrectly
- pgvector `search()` query params needed an explicit `::vector` cast — Postgres can't infer the type for a bare comparison operand the way it can for an INSERT target column
- Qdrant rejects arbitrary string point IDs (only unsigned int or UUID) — added a deterministic UUID5 mapping, with the caller's original id preserved in the payload
- `qdrant-client` >=1.10 removed `.search()` in favor of `.query_points()`
- Documented (not "fixed" — it's real DB behavior): Qdrant stores cosine-collection vectors normalized, not as-uploaded
- `PineconeAdapter.list_changed_since` treated Pinecone's paginated `ListResponse` objects as bare id strings — would have broken the downstream `fetch()` call against any real Pinecone index; never caught locally since Pinecone has no docker-based integration test target the way pgvector/Qdrant do
- `cli.py`'s `_load_adapter()` reused one variable name across the Qdrant and Pinecone branches, tripping strict mypy even though the branches are mutually exclusive at runtime

**Not yet implemented:** PyPI publish.
