"""Retrieval-quality parity verification — the actual differentiator.

Existing migration tools (vector-io/VDF, vendor migration guides) confirm
data *arrived*: row counts match, ids exist. None of them confirm the new
database still *retrieves the same things* — which is the only thing that
actually matters to the app sitting on top of it.

This module runs a query set against both the source and target adapters
and compares:

  - recall@k       — fraction of the source's top-k ids also in target's top-k
  - rank overlap    — Jaccard overlap of the top-k id sets
  - score drift      — mean absolute difference in similarity scores for
                       ids present in both result sets

A ParityReport aggregates these per-query results and exposes `passed`
against caller-supplied thresholds, so it can gate a migration in CI.
"""

from __future__ import annotations

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
    """Threshold this report was evaluated against."""

    @property
    def mean_recall_at_k(self) -> float:
        if not self.results:
            return 1.0
        return sum(r.recall_at_k for r in self.results) / len(self.results)

    @property
    def worst_query(self) -> QueryResult | None:
        if not self.results:
            return None
        return min(self.results, key=lambda r: r.recall_at_k)

    @property
    def passed(self) -> bool:
        return self.mean_recall_at_k >= self.min_recall_at_k

    def summary(self) -> str:
        lines = [
            f"Parity report: {len(self.results)} queries, "
            f"mean recall@k = {self.mean_recall_at_k:.3f} "
            f"(threshold {self.min_recall_at_k:.3f}) — "
            f"{'PASS' if self.passed else 'FAIL'}"
        ]
        worst = self.worst_query
        if worst is not None and not self.passed:
            lines.append(
                f"  worst query: {worst.label or '(unlabeled)'} — "
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
) -> ParityReport:
    """Run every query against both adapters and score retrieval parity.

    Raises ValueError if a QueryCase references a query_id that isn't
    found in the source — fail loud rather than silently skipping a case
    the caller expected to be evaluated.
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

        source_hits = source.search(vector, top_k=q.top_k)
        target_hits = target.search(vector, top_k=q.top_k)
        results.append(_compare_one(source_hits, target_hits, q.label))

    return ParityReport(results=results, min_recall_at_k=min_recall_at_k)
