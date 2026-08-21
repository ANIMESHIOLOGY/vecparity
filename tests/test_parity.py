"""Parity verification tests using the in-memory adapter — no docker required.

These validate the core differentiator (recall@k / overlap / score-drift
math) in isolation. Adapter-specific integration tests belong in
test_adapters_pgvector.py / test_adapters_qdrant.py, gated behind the
`integration` marker (require docker), not here.
"""

from __future__ import annotations

from vecparity.adapters.memory import MemoryAdapter
from vecparity.types import QueryCase, VectorRecord
from vecparity.verify.parity import verify_parity


def _record(id: str, vector: list[float]) -> VectorRecord:
    return VectorRecord(id=id, vector=vector, metadata={})


def test_identical_adapters_have_perfect_parity():
    source = MemoryAdapter()
    target = MemoryAdapter()
    records = [_record(f"doc-{i}", [float(i), float(i) + 1, 0.0]) for i in range(20)]
    source.upsert(records)
    target.upsert(records)

    queries = [QueryCase(query_id="doc-3", top_k=5, label="doc-3 neighbors")]
    report = verify_parity(source, target, queries, min_recall_at_k=1.0)

    assert report.passed
    assert report.mean_recall_at_k == 1.0
    assert report.results[0].mean_score_drift == 0.0


def test_missing_records_in_target_reduce_recall():
    source = MemoryAdapter()
    target = MemoryAdapter()
    records = [_record(f"doc-{i}", [float(i), float(i) + 1, 0.0]) for i in range(20)]
    source.upsert(records)
    # Target is missing everything except the query anchor itself.
    target.upsert([r for r in records if r.id == "doc-3"])

    queries = [QueryCase(query_id="doc-3", top_k=5)]
    report = verify_parity(source, target, queries, min_recall_at_k=0.99)

    assert not report.passed
    assert report.mean_recall_at_k < 1.0


def test_missing_query_id_raises():
    source = MemoryAdapter()
    target = MemoryAdapter()

    try:
        verify_parity(source, target, [QueryCase(query_id="nope")])
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_explicit_query_vector_does_not_require_source_membership():
    source = MemoryAdapter()
    target = MemoryAdapter()
    records = [_record(f"doc-{i}", [float(i), 0.0, 0.0]) for i in range(5)]
    source.upsert(records)
    target.upsert(records)

    report = verify_parity(source, target, [QueryCase(query_vector=[2.0, 0.0, 0.0], top_k=3)])
    assert report.passed
