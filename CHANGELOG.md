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
- GitHub Actions CI: lint/type-check, unit test matrix (Python 3.9–3.12), integration test job with service containers
- Verified end-to-end against real infrastructure: seeded 200 vectors into pgvector, migrated live to Qdrant via the CLI, parity report confirmed 100% recall@k / overlap, zero score drift

**Real bugs found and fixed during integration testing** (the reason this testing exists):
- pgvector adapter never registered pgvector-python's type adapter, so vector columns round-tripped incorrectly
- pgvector `search()` query params needed an explicit `::vector` cast — Postgres can't infer the type for a bare comparison operand the way it can for an INSERT target column
- Qdrant rejects arbitrary string point IDs (only unsigned int or UUID) — added a deterministic UUID5 mapping, with the caller's original id preserved in the payload
- `qdrant-client` >=1.10 removed `.search()` in favor of `.query_points()`
- Documented (not "fixed" — it's real DB behavior): Qdrant stores cosine-collection vectors normalized, not as-uploaded

**Not yet implemented:** PyPI publish, docs site.
