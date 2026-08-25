"""Retrieval-quality parity verification.

Runs a query set against both the source and target adapters and
compares recall@k, Jaccard overlap of top-k ids, and mean score drift.
ParityReport exposes `passed` against a caller-supplied threshold.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from vecparity.adapters.base import VectorDBAdapter
from vecparity.types import QueryCase, ScoredMatch


class QueryResult(BaseModel):
    label: str | None
    recall_at_k: float
    jaccard_overlap: float
    mean_score_drift: float
    source_top_k: list[str]
    target_top_k: list[str]


class ParityReport(BaseModel):
    results: list[QueryResult]
    min_recall_at_k: float
    """Threshold the mean is evaluated against."""
    min_per_query_recall: float | None = None
    """Optional floor every individual query must clear, so one query at
    0% can't hide inside a passing mean."""

    @property
    def mean_recall_at_k(self) -> float:
        if not self.results:
            return 1.0
        return sum(r.recall_at_k for r in self.results) / len(self.results)

    @property
    def p50_recall(self) -> float:
        return self._percentile(50)

    @property
    def p95_recall(self) -> float:
        return self._percentile(5)

    @property
    def min_recall(self) -> float:
        if not self.results:
            return 1.0
        return min(r.recall_at_k for r in self.results)

    @property
    def queries_below_threshold_pct(self) -> float:
        """Share of queries that individually fall below `min_recall_at_k`,
        even if the mean clears it."""
        if not self.results:
            return 0.0
        below = sum(1 for r in self.results if r.recall_at_k < self.min_recall_at_k)
        return below / len(self.results) * 100

    def _percentile(self, low_percentile: int) -> float:
        # p95 recall means the worst 5%, i.e. the 5th percentile of the
        # recall distribution, not the 95th; `low_percentile` is that
        # percentile directly so callers don't have to invert it.
        if not self.results:
            return 1.0
        return float(np.percentile([r.recall_at_k for r in self.results], low_percentile))

    @property
    def worst_query(self) -> QueryResult | None:
        if not self.results:
            return None
        return min(self.results, key=lambda r: r.recall_at_k)

    @property
    def passed(self) -> bool:
        if self.mean_recall_at_k < self.min_recall_at_k:
            return False
        if self.min_per_query_recall is not None and self.min_recall < self.min_per_query_recall:
            return False
        return True

    def summary(self) -> str:
        lines = [
            f"Parity report: {len(self.results)} queries, "
            f"mean recall@k = {self.mean_recall_at_k:.3f} "
            f"(threshold {self.min_recall_at_k:.3f}): "
            f"{'PASS' if self.passed else 'FAIL'}",
            f"  p50={self.p50_recall:.3f} p95={self.p95_recall:.3f} "
            f"min={self.min_recall:.3f} "
            f"below_threshold={self.queries_below_threshold_pct:.1f}%",
        ]
        worst = self.worst_query
        if worst is not None and not self.passed:
            lines.append(
                f"  worst query: {worst.label or '(unlabeled)'}: "
                f"recall@k={worst.recall_at_k:.3f}, "
                f"overlap={worst.jaccard_overlap:.3f}, "
                f"score_drift={worst.mean_score_drift:.4f}"
            )
        return "\n".join(lines)


def _compare_one(
    source_hits: list[ScoredMatch], target_hits: list[ScoredMatch], label: str | None
) -> QueryResult:
    source_ids = [h.id for h in source_hits]
    target_ids = [h.id for h in target_hits]
    source_set, target_set = set(source_ids), set(target_ids)

    recall = (len(source_set & target_set) / len(source_set)) if source_set else 1.0
    union = source_set | target_set
    jaccard = (len(source_set & target_set) / len(union)) if union else 1.0

    target_scores = {h.id: h.score for h in target_hits}
    shared = source_set & target_set
    if shared:
        drift = sum(
            abs(h.score - target_scores[h.id]) for h in source_hits if h.id in shared
        ) / len(shared)
    else:
        drift = 1.0

    return QueryResult(
        label=label,
        recall_at_k=recall,
        jaccard_overlap=jaccard,
        mean_score_drift=drift,
        source_top_k=source_ids,
        target_top_k=target_ids,
    )


def verify_parity(
    source: VectorDBAdapter,
    target: VectorDBAdapter,
    queries: list[QueryCase],
    min_recall_at_k: float = 0.9,
    min_per_query_recall: float | None = None,
) -> ParityReport:
    """Run every query against both adapters and score retrieval parity.
    Raises ValueError if a query_id isn't found in the source.

    `min_per_query_recall`, if set, gates `passed` on every individual
    query, not just the mean, so one query at 0% recall can't hide inside
    a passing average.
    """
    results: list[QueryResult] = []
    for q in queries:
        vector = q.query_vector
        if vector is None:
            if q.query_id is None:
                raise ValueError("QueryCase needs either query_vector or query_id")
            record = source.get(q.query_id)
            if record is None:
                raise ValueError(f"query_id {q.query_id!r} not found in source")
            vector = record.vector

        source_hits = source.search(vector, top_k=q.top_k, filter=q.filter)
        target_hits = target.search(vector, top_k=q.top_k, filter=q.filter)
        results.append(_compare_one(source_hits, target_hits, q.label))

    return ParityReport(
        results=results,
        min_recall_at_k=min_recall_at_k,
        min_per_query_recall=min_per_query_recall,
    )
