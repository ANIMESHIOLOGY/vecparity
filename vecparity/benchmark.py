"""Synthetic benchmark harness: seeds synthetic vectors into a source
adapter and times a real SyncEngine run into a target adapter.

Numbers this produces are only as good as the machine and backends you
run it against; a laptop run against local Docker containers and a
production cluster are not the same result. Treat this as a tool for
producing your own numbers, not a source of pre-baked ones.
"""

from __future__ import annotations

import time
import tracemalloc
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

from vecparity.adapters.base import VectorDBAdapter
from vecparity.sync.engine import SyncEngine
from vecparity.types import VectorRecord


@dataclass
class BenchmarkResult:
    num_records: int
    dimension: int
    batch_size: int
    seed_seconds: float
    sync_seconds: float
    records_per_second: float
    sync_batches: int
    peak_memory_mb: float


def generate_synthetic_records(
    num_records: int, dimension: int, seed: int = 0
) -> Iterator[VectorRecord]:
    rng = np.random.default_rng(seed)
    for i in range(num_records):
        yield VectorRecord(
            id=f"bench-{i}",
            vector=rng.random(dimension).tolist(),
            metadata={"bench": True},
        )


def run_benchmark(
    source: VectorDBAdapter,
    target: VectorDBAdapter,
    num_records: int,
    dimension: int = 128,
    batch_size: int = 500,
    seed_batch_size: int = 1000,
) -> BenchmarkResult:
    """Seed `num_records` synthetic vectors into `source`, then time a
    full `SyncEngine` run into `target`. Only the sync itself is timed;
    seeding time is reported separately since it isn't what a real
    migration measures."""
    seed_start = time.perf_counter()
    batch: list[VectorRecord] = []
    for record in generate_synthetic_records(num_records, dimension):
        batch.append(record)
        if len(batch) >= seed_batch_size:
            source.upsert(batch)
            batch = []
    if batch:
        source.upsert(batch)
    seed_seconds = time.perf_counter() - seed_start

    engine = SyncEngine(source, target, batch_size=batch_size)

    tracemalloc.start()
    sync_start = time.perf_counter()
    synced = engine.run_once()
    sync_seconds = time.perf_counter() - sync_start
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return BenchmarkResult(
        num_records=synced,
        dimension=dimension,
        batch_size=batch_size,
        seed_seconds=seed_seconds,
        sync_seconds=sync_seconds,
        records_per_second=synced / sync_seconds if sync_seconds > 0 else float("inf"),
        sync_batches=engine.stats.batches,
        peak_memory_mb=peak_bytes / (1024 * 1024),
    )
