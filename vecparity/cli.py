"""`vecparity migrate --from ... --to ... --live --verify-parity`

The CLI wires adapters + sync engine + parity verifier together. Adapter
construction from a connection string is deliberately simple (env-var
driven) rather than a big config DSL: see docs/backends.md for the
env vars each backend reads.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from vecparity.adapters.base import VectorDBAdapter
from vecparity.sync.engine import SyncEngine
from vecparity.types import QueryCase
from vecparity.verify.parity import verify_parity

app = typer.Typer(add_completion=False, help="Live, quality-verified vector DB migration.")
console = Console()


@app.command()
def version() -> None:
    """Print the installed vecparity version.

    Also has a side effect that matters: Typer silently collapses a
    single-command app so `vecparity migrate ...` and `vecparity ...`
    both work identically, dropping "migrate" from every example in the
    README. A second command keeps `migrate` a real, required subcommand
    (verified: `vecparity --from ... --to ...` 404s with "Got unexpected
    extra argument(s)" once there are two commands registered).
    """
    from vecparity import __version__

    console.print(__version__)


def _load_adapter(spec: str) -> VectorDBAdapter:
    """spec looks like 'pgvector://mytable' or 'qdrant://mycollection'.

    Connection details (host, port, api key) are read from env vars
    documented per-backend in docs/backends.md, kept out of the CLI
    surface so nothing sensitive ends up in shell history.
    """
    backend, _, name = spec.partition("://")
    if backend == "memory":
        from vecparity.adapters.memory import MemoryAdapter

        return MemoryAdapter()
    if backend == "qdrant":
        import os

        from qdrant_client import QdrantClient

        from vecparity.adapters.qdrant import QdrantAdapter

        # Separate variable names per branch (qdrant_client, pinecone_client,
        # below) rather than reusing `client`: mypy infers one type for a
        # name from its first assignment in the function and flags any
        # later branch that assigns it a different client type, even though
        # only one branch ever actually executes.
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


@app.command()
def migrate(
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
) -> None:
    """Sync `--from` into `--to`, optionally verifying retrieval parity."""
    source = _load_adapter(from_)
    target = _load_adapter(to)

    engine = SyncEngine(source=source, target=target)
    if live:
        console.print("[bold]Running until caught up...[/bold]")
        engine.run_until_caught_up()
    else:
        synced = engine.run_once()
        console.print(f"Synced {synced} records.")

    if verify:
        if queries_file is None:
            raise typer.BadParameter("--verify-parity requires --queries")
        cases = [QueryCase(**c) for c in json.loads(queries_file.read_text())]
        report = verify_parity(source, target, cases, min_recall_at_k=min_recall)

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

        if not report.passed:
            sys.exit(1)


if __name__ == "__main__":
    app()
