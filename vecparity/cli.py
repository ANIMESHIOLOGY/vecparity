"""`vecparity migrate run --from ... --to ... --live --verify-parity`

Connection details are read from env vars, documented per-backend in
docs/backends.md, rather than CLI flags.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from vecparity.adapters.base import VectorDBAdapter
from vecparity.benchmark import run_benchmark
from vecparity.checkpoint import (
    DEFAULT_CHECKPOINT_PATH,
    STATUS_CANCELLED,
    STATUS_CUT_OVER,
    STATUS_PAUSE_REQUESTED,
    STATUS_PAUSED,
    STATUS_ROLLED_BACK,
    STATUS_SYNCING,
    STATUS_VERIFIED,
    CheckpointStore,
)
from vecparity.report import report_to_html, report_to_json
from vecparity.schema import compare_schemas, inspect_adapter
from vecparity.sync.engine import SyncEngine
from vecparity.types import QueryCase, VectorRecord
from vecparity.verify.parity import ParityReport, verify_parity

app = typer.Typer(add_completion=False, help="Live, quality-verified vector DB migration.")
console = Console()


@app.command()
def version() -> None:
    """Print the installed vecparity version.

    Also keeps Typer from collapsing this into a single-command app,
    which would make a subcommand an implicit default instead of
    required.
    """
    from vecparity import __version__

    console.print(__version__)


def _load_adapter(spec: str) -> VectorDBAdapter:
    """spec looks like 'pgvector://mytable' or 'qdrant://mycollection'."""
    backend, _, name = spec.partition("://")
    if backend == "memory":
        from vecparity.adapters.memory import MemoryAdapter

        return MemoryAdapter()
    if backend == "qdrant":
        import os

        from qdrant_client import QdrantClient

        from vecparity.adapters.qdrant import QdrantAdapter

        # Separate variable names per branch to avoid mypy flagging a
        # reused name across branches that assign different client types.
        qdrant_client = QdrantClient(
            url=os.environ.get("QDRANT_URL", "http://localhost:6333"),
            api_key=os.environ.get("QDRANT_API_KEY"),
        )
        return QdrantAdapter(client=qdrant_client, collection=name)
    if backend == "pgvector":
        import os

        import psycopg

        from vecparity.adapters.pgvector import PgVectorAdapter

        conn = psycopg.connect(os.environ["PGVECTOR_DSN"])
        return PgVectorAdapter(conn=conn, table=name)
    if backend == "pinecone":
        import os

        from pinecone import Pinecone

        from vecparity.adapters.pinecone import PineconeAdapter

        pinecone_client = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
        namespace = os.environ.get("PINECONE_NAMESPACE", "")
        return PineconeAdapter(client=pinecone_client, index_name=name, namespace=namespace)
    if backend == "milvus":
        import os

        from pymilvus import MilvusClient

        from vecparity.adapters.milvus import MilvusAdapter

        milvus_client = MilvusClient(uri=os.environ.get("MILVUS_URI", "http://localhost:19530"))
        return MilvusAdapter(client=milvus_client, collection_name=name)
    if backend == "weaviate":
        import os

        import weaviate

        from vecparity.adapters.weaviate import WeaviateAdapter

        weaviate_client = weaviate.connect_to_local(
            host=os.environ.get("WEAVIATE_HOST", "localhost"),
            port=int(os.environ.get("WEAVIATE_PORT", "8080")),
            grpc_port=int(os.environ.get("WEAVIATE_GRPC_PORT", "50051")),
        )
        return WeaviateAdapter(collection=weaviate_client.collections.get(name))
    if backend == "chroma":
        import os

        import chromadb

        from vecparity.adapters.chroma import ChromaAdapter

        chroma_client = chromadb.HttpClient(
            host=os.environ.get("CHROMA_HOST", "localhost"),
            port=int(os.environ.get("CHROMA_PORT", "8000")),
        )
        return ChromaAdapter(collection=chroma_client.get_or_create_collection(name))
    raise typer.BadParameter(f"unknown backend {backend!r} in {spec!r}")


def _migration_id(from_: str, to: str) -> str:
    return f"{from_}=>{to}"


def _print_parity_report(report: ParityReport) -> None:
    table = Table(title="Parity Report")
    table.add_column("Query")
    table.add_column("Recall@k")
    table.add_column("Overlap")
    table.add_column("Score Drift")
    for r in report.results:
        table.add_row(
            r.label or "(unlabeled)",
            f"{r.recall_at_k:.3f}",
            f"{r.jaccard_overlap:.3f}",
            f"{r.mean_score_drift:.4f}",
        )
    console.print(table)
    console.print(report.summary())


checkpoint_app = typer.Typer(add_completion=False, help="Inspect or clear saved migration state.")
app.add_typer(checkpoint_app, name="checkpoint")


@checkpoint_app.command("show")
def checkpoint_show(
    from_: str = typer.Option(..., "--from"),
    to: str = typer.Option(..., "--to"),
    checkpoint_file: Path = typer.Option(DEFAULT_CHECKPOINT_PATH, "--checkpoint-file"),
) -> None:
    """Print the saved cursor and progress for a --from/--to pair, if any."""
    store = CheckpointStore(checkpoint_file)
    cp = store.load(_migration_id(from_, to))
    if cp is None:
        console.print("No checkpoint saved for this migration.")
        return
    console.print(
        f"cursor={cp.cursor} records_synced={cp.records_synced} "
        f"records_deleted={cp.records_deleted} last_batch_at={cp.last_batch_at}"
    )


@checkpoint_app.command("clear")
def checkpoint_clear(
    from_: str = typer.Option(..., "--from"),
    to: str = typer.Option(..., "--to"),
    checkpoint_file: Path = typer.Option(DEFAULT_CHECKPOINT_PATH, "--checkpoint-file"),
) -> None:
    """Delete the saved checkpoint, so the next migrate run starts from scratch."""
    store = CheckpointStore(checkpoint_file)
    store.delete(_migration_id(from_, to))
    console.print("Checkpoint cleared.")


@app.command()
def plan(
    from_: str = typer.Option(..., "--from", help="source, e.g. pgvector://docs"),
    to: str = typer.Option(..., "--to", help="target, e.g. qdrant://docs"),
    sample_size: int = typer.Option(
        100, "--sample-size", help="records sampled from each side to infer shape"
    ),
) -> None:
    """Compare source and target shape before touching any data: vector
    dimension, metadata field types, and whether the target is already
    populated. Exits non-zero if it finds a migration-blocking issue."""
    source = _load_adapter(from_)
    target = _load_adapter(to)

    console.print("Sampling source and target...")
    source_schema = inspect_adapter(source, sample_size=sample_size)
    target_schema = inspect_adapter(target, sample_size=sample_size)
    report = compare_schemas(source_schema, target_schema)

    console.print(report.summary())
    if report.blocking:
        sys.exit(1)


@app.command()
def validate(
    from_: str = typer.Option(..., "--from", help="source, e.g. pgvector://docs"),
    to: str = typer.Option(..., "--to", help="target, e.g. qdrant://docs"),
) -> None:
    """Pre-flight check: connectivity to both sides, and a real write
    probe against the target (not just "the client object connected"),
    since only an actual write proves the credentials can write."""
    ok = True

    console.print("Connecting to source...")
    try:
        source = _load_adapter(from_)
        source.count()
        console.print("[green]OK[/green] source reachable.")
    except Exception as e:
        console.print(f"[red]FAIL[/red] source: {e}")
        raise typer.Exit(1) from e

    console.print("Connecting to target...")
    try:
        target = _load_adapter(to)
        target.count()
        console.print("[green]OK[/green] target reachable.")
    except Exception as e:
        console.print(f"[red]FAIL[/red] target: {e}")
        raise typer.Exit(1) from e

    console.print("Checking target write permission...")
    dimension = inspect_adapter(source, sample_size=1).dimension
    if dimension is None:
        console.print("[yellow]SKIPPED[/yellow] source is empty, can't infer a probe dimension.")
    else:
        probe_id = "__vecparity_validate_probe__"
        try:
            target.upsert([VectorRecord(id=probe_id, vector=[0.0] * dimension)])
            target.delete([probe_id])
            console.print("[green]OK[/green] target accepts writes.")
        except Exception as e:
            console.print(f"[red]FAIL[/red] target write check: {e}")
            ok = False

    if not ok:
        sys.exit(1)


migrate_app = typer.Typer(add_completion=False, help="Run and control a live migration.")
app.add_typer(migrate_app, name="migrate")

_TERMINAL_STATUSES = (STATUS_CANCELLED, STATUS_CUT_OVER, STATUS_ROLLED_BACK)


@migrate_app.command("run")
def migrate_run(
    from_: str = typer.Option(..., "--from", help="source, e.g. pgvector://docs"),
    to: str = typer.Option(..., "--to", help="target, e.g. qdrant://docs"),
    live: bool = typer.Option(
        False, "--live", help="poll for changes until caught up instead of a single pass"
    ),
    verify: bool = typer.Option(
        False, "--verify-parity", help="run parity verification after sync"
    ),
    queries_file: Path | None = typer.Option(
        None, "--queries", help="JSON file of query cases for --verify-parity"
    ),
    min_recall: float = typer.Option(0.9, "--min-recall", help="parity pass threshold"),
    min_per_query_recall: float | None = typer.Option(
        None,
        "--min-per-query-recall",
        help="also require every individual query to clear this floor, not just the mean",
    ),
    quarantine_file: Path | None = typer.Option(
        None, "--quarantine-file", help="where records that fail every retry get logged"
    ),
    checkpoint_file: Path = typer.Option(
        DEFAULT_CHECKPOINT_PATH,
        "--checkpoint-file",
        help="SQLite file storing resumable migration state",
    ),
    fresh: bool = typer.Option(
        False, "--fresh", help="ignore any saved checkpoint and start from the beginning"
    ),
) -> None:
    """Sync `--from` into `--to`, optionally verifying retrieval parity."""
    source = _load_adapter(from_)
    target = _load_adapter(to)

    migration_id = _migration_id(from_, to)
    store = CheckpointStore(checkpoint_file)
    saved = None if fresh else store.load(migration_id)

    if saved is not None and saved.status in _TERMINAL_STATUSES:
        console.print(
            f"[red]This migration is marked '{saved.status}'.[/red] " "Pass --fresh to start over."
        )
        raise typer.Exit(1)

    if saved is not None:
        console.print(
            f"[bold]Resuming[/bold] from checkpoint "
            f"(cursor={saved.cursor}, {saved.records_synced} already synced)."
        )
        engine = SyncEngine.from_checkpoint(source, target, saved, quarantine_path=quarantine_file)
    else:
        engine = SyncEngine(source=source, target=target, quarantine_path=quarantine_file)

    status = STATUS_SYNCING
    last_verify_passed = saved.last_verify_passed if saved is not None else None
    stopped_early = False

    def _save_checkpoint() -> None:
        cp = engine.checkpoint(migration_id, from_, to)
        cp.status = status
        cp.last_verify_passed = last_verify_passed
        store.save(cp)

    _save_checkpoint()  # status visible to `migrate status` right away, before the first batch

    def _should_stop() -> bool:
        nonlocal status, stopped_early
        current = store.load(migration_id)
        if current is None:
            return False
        if current.status == STATUS_CANCELLED:
            stopped_early = True
            console.print("[yellow]Cancelled; stopping.[/yellow]")
            return True
        if current.status == STATUS_PAUSE_REQUESTED:
            status = STATUS_PAUSED
            _save_checkpoint()
            stopped_early = True
            console.print("[yellow]Paused. Re-run `migrate run` to resume.[/yellow]")
            return True
        return False

    if live:
        console.print("[bold]Running until caught up...[/bold]")
        engine.run_until_caught_up(on_batch=_save_checkpoint, should_stop=_should_stop)
    else:
        synced = engine.run_once()
        _save_checkpoint()
        console.print(f"Synced {synced} records.")

    if engine.stats.records_deleted:
        console.print(f"Propagated {engine.stats.records_deleted} deletes.")
    if engine.stats.records_quarantined:
        console.print(
            f"[yellow]Quarantined {engine.stats.records_quarantined} records "
            f"(see {quarantine_file}).[/yellow]"
        )

    if stopped_early:
        return

    if verify:
        if queries_file is None:
            raise typer.BadParameter("--verify-parity requires --queries")
        cases = [QueryCase(**c) for c in json.loads(queries_file.read_text())]
        report = verify_parity(
            source,
            target,
            cases,
            min_recall_at_k=min_recall,
            min_per_query_recall=min_per_query_recall,
        )
        _print_parity_report(report)

        status = STATUS_VERIFIED if report.passed else status
        last_verify_passed = report.passed
        _save_checkpoint()

        if not report.passed:
            sys.exit(1)


@migrate_app.command("status")
def migrate_status(
    from_: str = typer.Option(..., "--from"),
    to: str = typer.Option(..., "--to"),
    checkpoint_file: Path = typer.Option(DEFAULT_CHECKPOINT_PATH, "--checkpoint-file"),
) -> None:
    """Show a migration's operational status: syncing, paused, verified,
    cut over, etc., plus its cursor and progress."""
    store = CheckpointStore(checkpoint_file)
    cp = store.load(_migration_id(from_, to))
    if cp is None:
        console.print("No migration recorded for this --from/--to pair.")
        return
    console.print(f"status: {cp.status}")
    console.print(f"cursor: {cp.cursor}")
    console.print(f"records_synced: {cp.records_synced}")
    console.print(f"records_deleted: {cp.records_deleted}")
    console.print(f"last_verify_passed: {cp.last_verify_passed}")
    console.print(f"last_batch_at: {cp.last_batch_at}")


@migrate_app.command("pause")
def migrate_pause(
    from_: str = typer.Option(..., "--from"),
    to: str = typer.Option(..., "--to"),
    checkpoint_file: Path = typer.Option(DEFAULT_CHECKPOINT_PATH, "--checkpoint-file"),
) -> None:
    """Request a running `migrate run --live` to stop cleanly at its next
    poll. Only takes effect while that process is actually running there's
    no separate daemon to signal; if nothing is running, this just
    records the request until the next `migrate run`."""
    store = CheckpointStore(checkpoint_file)
    migration_id = _migration_id(from_, to)
    cp = store.load(migration_id)
    if cp is None:
        console.print("No migration recorded for this --from/--to pair.")
        raise typer.Exit(1)
    if cp.status not in (STATUS_SYNCING, STATUS_PAUSE_REQUESTED):
        console.print(f"[yellow]Nothing to pause (status is '{cp.status}').[/yellow]")
        raise typer.Exit(1)
    cp.status = STATUS_PAUSE_REQUESTED
    store.save(cp)
    console.print("Pause requested.")


@migrate_app.command("cancel")
def migrate_cancel(
    from_: str = typer.Option(..., "--from"),
    to: str = typer.Option(..., "--to"),
    checkpoint_file: Path = typer.Option(DEFAULT_CHECKPOINT_PATH, "--checkpoint-file"),
) -> None:
    """Mark a migration cancelled. The checkpoint itself is kept (use
    `checkpoint clear` to discard it); a future `migrate run` refuses to
    resume it without --fresh."""
    store = CheckpointStore(checkpoint_file)
    migration_id = _migration_id(from_, to)
    cp = store.load(migration_id)
    if cp is None:
        console.print("No migration recorded for this --from/--to pair.")
        raise typer.Exit(1)
    cp.status = STATUS_CANCELLED
    store.save(cp)
    console.print("Migration cancelled.")


@app.command()
def cutover(
    from_: str = typer.Option(..., "--from", help="source, e.g. pgvector://docs"),
    to: str = typer.Option(..., "--to", help="target, e.g. qdrant://docs"),
    queries_file: Path = typer.Option(
        ..., "--queries", help="JSON file of query cases for the final parity check"
    ),
    min_recall: float = typer.Option(0.9, "--min-recall", help="parity pass threshold"),
    min_per_query_recall: float | None = typer.Option(
        None,
        "--min-per-query-recall",
        help="also require every individual query to clear this floor",
    ),
    checkpoint_file: Path = typer.Option(DEFAULT_CHECKPOINT_PATH, "--checkpoint-file"),
    report_json: Path | None = typer.Option(
        None, "--report-json", help="write a JSON report combining migration state and parity"
    ),
    report_html: Path | None = typer.Option(
        None,
        "--report-html",
        help="write a self-contained HTML report, same content as --report-json",
    ),
) -> None:
    """Run one final sync pass and a final parity check; mark the
    migration cut over only if it passes.

    vecparity has no way to redirect your application's traffic itself;
    this command only tells you, with evidence, whether it's safe to do
    so yourself.
    """
    migration_id = _migration_id(from_, to)
    store = CheckpointStore(checkpoint_file)
    saved = store.load(migration_id)
    if saved is None:
        console.print("No migration recorded for this --from/--to pair. Run `migrate run` first.")
        raise typer.Exit(1)
    if saved.status in _TERMINAL_STATUSES:
        console.print(f"[red]Migration status is '{saved.status}'; nothing to cut over.[/red]")
        raise typer.Exit(1)

    source = _load_adapter(from_)
    target = _load_adapter(to)
    engine = SyncEngine.from_checkpoint(source, target, saved)

    console.print("[bold]Final sync...[/bold]")
    synced = engine.run_once()
    console.print(f"Synced {synced} more records.")

    console.print("[bold]Final parity check...[/bold]")
    cases = [QueryCase(**c) for c in json.loads(queries_file.read_text())]
    report = verify_parity(
        source,
        target,
        cases,
        min_recall_at_k=min_recall,
        min_per_query_recall=min_per_query_recall,
    )
    _print_parity_report(report)

    cp = engine.checkpoint(migration_id, from_, to)
    if report.passed:
        cp.status = STATUS_CUT_OVER
        cp.last_verify_passed = True
        store.save(cp)
        console.print(
            "[bold green]Cutover complete.[/bold green] Safe to redirect your "
            "application's traffic to the target now."
        )
    else:
        cp.status = STATUS_SYNCING
        cp.last_verify_passed = False
        store.save(cp)

    if report_json is not None:
        report_json.write_text(report_to_json(cp, report))
        console.print(f"Wrote {report_json}")
    if report_html is not None:
        report_html.write_text(report_to_html(cp, report))
        console.print(f"Wrote {report_html}")

    if not report.passed:
        console.print("[bold red]Cutover aborted: parity check failed.[/bold red]")
        sys.exit(1)


@app.command()
def rollback(
    from_: str = typer.Option(..., "--from"),
    to: str = typer.Option(..., "--to"),
    checkpoint_file: Path = typer.Option(DEFAULT_CHECKPOINT_PATH, "--checkpoint-file"),
) -> None:
    """Mark a cut-over migration rolled back.

    vecparity does not sync data back to the source: this only records
    the decision and tells you what to do next, it doesn't reverse
    anything for you.
    """
    migration_id = _migration_id(from_, to)
    store = CheckpointStore(checkpoint_file)
    cp = store.load(migration_id)
    if cp is None or cp.status != STATUS_CUT_OVER:
        console.print("Nothing to roll back: this migration was never cut over.")
        raise typer.Exit(1)
    cp.status = STATUS_ROLLED_BACK
    store.save(cp)
    console.print(
        "[bold yellow]Rolled back.[/bold yellow] vecparity does not sync data back "
        "to the source: redirect your application's traffic back to the source "
        "yourself. The target's data as of cutover is still there for inspection, "
        "but should no longer be treated as the source of truth."
    )


@app.command()
def benchmark(
    from_: str = typer.Option(
        "memory://bench-source", "--from", help="source adapter to seed and sync from"
    ),
    to: str = typer.Option("memory://bench-target", "--to", help="target adapter to sync into"),
    num_records: int = typer.Option(
        100_000, "--num-records", help="synthetic vectors to seed and sync"
    ),
    dimension: int = typer.Option(128, "--dimension", help="vector dimension"),
    batch_size: int = typer.Option(500, "--batch-size", help="SyncEngine batch size"),
) -> None:
    """Seed synthetic vectors into `--from` and time a real sync into
    `--to`. Numbers are only as good as the machine and backends you run
    this against; they aren't a substitute for testing at your actual
    scale on your actual infrastructure.
    """
    source = _load_adapter(from_)
    target = _load_adapter(to)

    console.print(f"Seeding {num_records} synthetic {dimension}-dim vectors into {from_}...")
    result = run_benchmark(
        source, target, num_records=num_records, dimension=dimension, batch_size=batch_size
    )

    console.print(f"Seed time: {result.seed_seconds:.2f}s")
    console.print(f"Sync time: {result.sync_seconds:.2f}s")
    console.print(f"Throughput: {result.records_per_second:.0f} records/sec")
    console.print(f"Batches: {result.sync_batches}")
    console.print(f"Peak memory during sync: {result.peak_memory_mb:.1f} MB")


if __name__ == "__main__":
    app()
