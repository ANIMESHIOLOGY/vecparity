"""Benchmark harness tests using the in-memory adapter, at a small scale
that's fast enough for a regular test run."""

from __future__ import annotations

from vecparity.adapters.memory import MemoryAdapter
from vecparity.benchmark import generate_synthetic_records, run_benchmark


def test_generate_synthetic_records_produces_the_requested_count_and_dimension():
    records = list(generate_synthetic_records(num_records=25, dimension=8))

    assert len(records) == 25
    assert all(len(r.vector) == 8 for r in records)
    assert len({r.id for r in records}) == 25  # unique ids


def test_generate_synthetic_records_is_deterministic_per_seed():
    a = [r.vector for r in generate_synthetic_records(10, 4, seed=1)]
    b = [r.vector for r in generate_synthetic_records(10, 4, seed=1)]
    assert a == b


def test_run_benchmark_actually_syncs_and_reports_sane_numbers():
    source, target = MemoryAdapter(), MemoryAdapter()

    result = run_benchmark(source, target, num_records=200, dimension=16, batch_size=50)

    assert result.num_records == 200
    assert target.count() == 200
    assert result.dimension == 16
    assert result.batch_size == 50
    assert result.sync_batches == 4  # 200 / 50
    assert result.seed_seconds >= 0
    assert result.sync_seconds >= 0
    assert result.records_per_second > 0
    assert result.peak_memory_mb >= 0
