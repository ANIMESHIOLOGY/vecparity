# Changelog

## Unreleased

- Added rich migration reports: `vecparity/report.py` combines a migration's checkpoint state and its parity results into a self-contained HTML page or a JSON export (no external assets, works offline). `vecparity cutover` gained `--report-json`/`--report-html` to write one out after the final parity check.
- Added a synthetic benchmark harness: `vecparity benchmark --from ... --to ... --num-records N` seeds synthetic vectors into a source and times a real `SyncEngine` run into a target, reporting throughput, batch count, and peak memory. Deliberately not a claim about 1M/10M/100M-scale numbers: those need real infrastructure to measure honestly, not a synthetic dev-machine run. See `docs/benchmarking.md`, including one real data point (200k vectors into a local Qdrant container) for context on what the tool measures.

- **Breaking:** `vecparity migrate --from ... --to ...` is now `vecparity migrate run --from ... --to ...`. `migrate` became a command group so it could gain `status`, `pause`, and `cancel` alongside `run`.
- Added an operational status to every migration, persisted alongside its checkpoint: `not_started`, `syncing`, `paused`, `verified`, `cut_over`, `rolled_back`, or `cancelled`.
  - `vecparity migrate status` shows it, plus cursor and progress.
  - `vecparity migrate pause` asks a running `migrate run --live` to stop cleanly at its next poll (cooperative, checked once per pass; there's no daemon to signal directly). `migrate run` (no `--fresh`) resumes it from the checkpoint.
  - `vecparity migrate cancel` marks a migration cancelled; a future `migrate run` refuses to resume it without `--fresh`.
  - `vecparity cutover` runs one final sync pass and a final parity check, and only marks the migration cut over if it passes.
  - `vecparity rollback` marks a cut-over migration rolled back.
  - `cutover`/`rollback` are deliberately honest about what vecparity can't do: it has no way to redirect application traffic and doesn't sync data back to the source. They track state and give you a fresh parity check to decide on, not an automated switchover.
- `SyncEngine.run_until_caught_up()` gained an optional `should_stop` callback, checked after every pass, which is what makes cooperative pause/cancel possible.

- Added filter-aware parity checks: `search()` now takes an optional `filter` (equality-only metadata filter, an implicit AND across keys), implemented across all six real backends plus the in-memory adapter. `QueryCase.filter` lets `verify_parity()` replay a golden query's real filter against both source and target, instead of only ever checking plain unfiltered similarity, which could miss a gap that only shows up on a filtered query path. Deliberately narrow scope, on purpose: equality only, no cross-backend query DSL, no sparse/hybrid search yet (backend support for that varies too widely to build generically without a concrete need driving it).

- Added schema inspection: `inspect_adapter()` samples a collection through the existing `list_changed_since`/`count` protocol (no new adapter methods) to infer vector dimension and metadata field types. `compare_schemas()` turns two of these into a `CompatibilityReport`, flagging a dimension mismatch as blocking and metadata type drift or a non-empty target as warnings.
- New `vecparity plan --from ... --to ...` prints that compatibility report and exits non-zero on a blocking issue, before any data moves.
- New `vecparity validate --from ... --to ...` checks connectivity to both sides, then proves target write access with a real probe upsert/delete (dimension-matched to the source) rather than just checking the client object connected.

- Added durable migration checkpoints: `SyncEngine.checkpoint()` / `SyncEngine.from_checkpoint()` snapshot and restore full sync state (cursor, both boundary-id sets, and progress counters), backed by a new `CheckpointStore` (SQLite, default `~/.vecparity/checkpoints.db`). `vecparity migrate` now saves a checkpoint after every batch and resumes from it automatically on the next run for the same `--from`/`--to` pair, unless `--fresh` is passed. Restoring the boundary-id sets (not just the raw cursor) matters: without them, a crash-and-resume right at a timestamp tie would reintroduce the exact tie-bug that was just fixed.
- New `vecparity checkpoint show` / `vecparity checkpoint clear` commands to inspect or discard saved migration state.

- Fixed a cursor tie-bug in `list_changed_since`: all six adapters (plus the in-memory reference adapter) switched from a strict `>` comparison to inclusive `>=`. A record sharing its timestamp with the last-seen cursor value, written after that boundary was set, was being silently skipped forever. `SyncEngine` now tracks per-boundary ids it's already synced, so the re-fetched boundary records from the inclusive query aren't reprocessed either.
- Added delete propagation: `VectorDBAdapter.list_deleted_since(cursor)` is a new optional method (default: untracked, not an error) that yields `(id, deleted_at)` pairs; `SyncEngine` calls it alongside `list_changed_since` and mirrors deletes to the target, using the same tie-safe boundary tracking. Implemented as a tombstone table for the in-memory adapter as a reference; the six real-backend adapters don't implement it yet.
- Strengthened the parity gate: `ParityReport` now exposes `p50_recall`, `p95_recall`, `min_recall`, and `queries_below_threshold_pct`. `verify_parity()` takes an optional `min_per_query_recall` floor so one query at 0% recall can't hide inside a passing mean.
- Added retry with exponential backoff around `SyncEngine`'s target upserts, and per-record quarantine (`--quarantine-file`) for anything that still fails after retries, so one bad record no longer kills the whole migration.
- `vecparity migrate` gained `--min-per-query-recall` and `--quarantine-file` flags, and now reports delete/quarantine counts after a run.
- Verified against real infrastructure: 13 unit tests plus 32 integration tests against real Qdrant, Weaviate, Chroma, and Milvus containers, all passing. pgvector's integration test couldn't run locally (a Windows Application Control policy blocks psycopg's binary DLL on this machine); its fix is a one-character SQL change (`>` to `>=`) in a query already covered by the existing integration test.

## v0.1.0 - Initial release

- Core types (`VectorRecord`, `ScoredMatch`, `QueryCase`)
- `VectorDBAdapter` protocol (get, upsert, delete, list_changed_since, search, count)
- Adapters: in-memory (reference/testing), pgvector, Qdrant, Pinecone, Milvus, Weaviate, Chroma
- `SyncEngine`: cursor-based incremental replication (`run_once`, `run_until_caught_up`)
- `verify_parity`: recall@k, Jaccard overlap, and score-drift comparison producing a pass/fail `ParityReport`
- CLI: `vecparity migrate --from ... --to ... [--live] [--verify-parity]`, `vecparity version`
- Unit tests for parity math and sync engine against the in-memory adapter
- Integration tests for all six real backends against real Docker containers (`docker-compose.test.yml`), 40/40 passing
- GitHub Actions CI: lint/type-check, unit test matrix (Python 3.10-3.13), integration test job running the full docker-compose stack
- Verified end-to-end against real infrastructure: seeded 200 vectors into pgvector, migrated live to Qdrant via the CLI, parity report confirmed 100% recall@k / overlap, zero score drift
- Requires Python >=3.10: PEP 604 `X | None` union syntax is used throughout, including in pydantic models and Typer CLI option types. Both resolve annotations at runtime, which needs real interpreter support for `|` on types (3.10+). Python 3.9 also reached end-of-life on 2025-10-31.
- `CONTRIBUTING.md`, GitHub issue templates, and an mkdocs documentation site (`mkdocs.yml`, `docs/`, deployed via `.github/workflows/docs.yml`)
- Project logo, in the README and the docs site (nav header, favicon, homepage banner)

**Real bugs found and fixed during development** (mostly via integration testing against real backends, one via CI's Python 3.9 matrix job before that version was dropped):
- pgvector adapter never registered pgvector-python's type adapter, so vector columns round-tripped incorrectly
- pgvector `search()` query params needed an explicit `::vector` cast, since Postgres can't infer the type for a bare comparison operand the way it can for an INSERT target column
- Qdrant rejects arbitrary string point IDs (only unsigned int or UUID). Added a deterministic UUID5 mapping, with the caller's original id preserved in the payload
- `qdrant-client` >=1.10 removed `.search()` in favor of `.query_points()`
- Documented (not "fixed", it's real DB behavior): Qdrant stores cosine-collection vectors normalized, not as-uploaded
- `PineconeAdapter.list_changed_since` treated Pinecone's paginated `ListResponse` objects as bare id strings. Would have broken the downstream `fetch()` call against any real Pinecone index; never caught locally since Pinecone has no docker-based integration test target the way pgvector/Qdrant do
- `cli.py`'s `_load_adapter()` reused one variable name across the Qdrant and Pinecone branches, tripping strict mypy even though the branches are mutually exclusive at runtime
- Milvus defaults to "Bounded" consistency: an immediate `get()`/`count()`/`search()` after `upsert()` could see nothing or a stale prior value. Every `MilvusAdapter` read now passes `consistency_level="Strong"`. Caught by the adapter's own integration tests, which initially failed with exactly that symptom (7 of 8 failing on first run)
- The single-container "embedded etcd" Milvus standalone mode from Milvus's own quickstart script panicked ("embedded etcd can not be used under distributed mode") against the image version used here. Switched `docker-compose.test.yml` to Milvus's officially documented 3-service setup (etcd + minio + milvus) instead of debugging an undocumented single-container variant
- Weaviate's Docker image is Alpine-based with no bash, so the `/dev/tcp` healthcheck trick the other services use silently reported "unhealthy" on an actually-healthy service. Switched to a `wget`-based healthcheck against Weaviate's own readiness endpoint
- CI's integration job hit a transient Docker networking race on the GitHub-hosted runner ("address already in use" for a port nothing else in the job used). Confirmed transient by re-running the identical workflow with zero code changes; added a retry loop around `docker compose up` as insurance against a recurrence

**Not yet implemented:** PyPI publish.
