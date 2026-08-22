"""Shared data types used across adapters, sync, and verification."""

from __future__ import annotations

from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict


class VectorRecord(BaseModel):
    """One vector + its metadata, in backend-agnostic form."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    vector: list[float]
    metadata: dict[str, Any] = {}
    updated_at: float | None = None
    """Unix timestamp of last write, used for incremental sync cursors."""

    def as_array(self) -> np.ndarray:
        return np.asarray(self.vector, dtype=np.float32)


class ScoredMatch(BaseModel):
    """One result from a similarity search, with its rank preserved."""

    id: str
    score: float
    metadata: dict[str, Any] = {}


class QueryCase(BaseModel):
    """A single query used for parity verification.

    Either a query_vector is supplied directly, or query_id references a
    VectorRecord already in the source collection to search *with*.
    """

    query_vector: list[float] | None = None
    query_id: str | None = None
    top_k: int = 10
    label: str | None = None
    """Optional human-readable name, shown in parity reports/CI failures."""
