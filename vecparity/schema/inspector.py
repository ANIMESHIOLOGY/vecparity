"""Read-only schema inspection: infers a collection's shape (dimension,
metadata field types, size) from a sample of its records, using only the
existing VectorDBAdapter protocol. No new adapter methods, on purpose:
this stays a read-only pre-flight check, not a schema-mapping layer.
"""

from __future__ import annotations

from itertools import islice

from pydantic import BaseModel

from vecparity.adapters.base import VectorDBAdapter


class CollectionSchema(BaseModel):
    record_count: int
    dimension: int | None
    metadata_field_types: dict[str, str]
    sample_size: int


def inspect_adapter(adapter: VectorDBAdapter, sample_size: int = 100) -> CollectionSchema:
    """Sample up to `sample_size` records to infer dimension and metadata
    field types. A field whose type varies across the sample is recorded
    as the union of types seen, joined with '|'."""
    field_types: dict[str, set[str]] = {}
    dimension: int | None = None
    sampled = 0

    for record in islice(adapter.list_changed_since(None), sample_size):
        sampled += 1
        if dimension is None:
            dimension = len(record.vector)
        for key, value in record.metadata.items():
            field_types.setdefault(key, set()).add(type(value).__name__)

    return CollectionSchema(
        record_count=adapter.count(),
        dimension=dimension,
        metadata_field_types={k: "|".join(sorted(v)) for k, v in field_types.items()},
        sample_size=sampled,
    )


class CompatibilityIssue(BaseModel):
    severity: str  # "error" blocks a migration, "warning" doesn't
    message: str


class CompatibilityReport(BaseModel):
    source: CollectionSchema
    target: CollectionSchema
    issues: list[CompatibilityIssue]

    @property
    def blocking(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    def summary(self) -> str:
        lines = [
            f"Source: {self.source.record_count} records, "
            f"dimension={self.source.dimension}, "
            f"{len(self.source.metadata_field_types)} metadata fields "
            f"(sampled {self.source.sample_size})",
            f"Target: {self.target.record_count} records, "
            f"dimension={self.target.dimension}, "
            f"{len(self.target.metadata_field_types)} metadata fields "
            f"(sampled {self.target.sample_size})",
        ]
        if not self.issues:
            lines.append("No compatibility issues found.")
        for issue in self.issues:
            lines.append(f"[{issue.severity.upper()}] {issue.message}")
        return "\n".join(lines)


def compare_schemas(source: CollectionSchema, target: CollectionSchema) -> CompatibilityReport:
    issues: list[CompatibilityIssue] = []

    if (
        source.dimension is not None
        and target.dimension is not None
        and source.dimension != target.dimension
    ):
        issues.append(
            CompatibilityIssue(
                severity="error",
                message=(
                    f"vector dimension mismatch: source={source.dimension}, "
                    f"target={target.dimension}"
                ),
            )
        )

    for field, source_type in source.metadata_field_types.items():
        target_type = target.metadata_field_types.get(field)
        if target_type is not None and target_type != source_type:
            issues.append(
                CompatibilityIssue(
                    severity="warning",
                    message=(
                        f"metadata field {field!r} type differs: "
                        f"source={source_type}, target={target_type}"
                    ),
                )
            )

    if target.record_count > 0:
        issues.append(
            CompatibilityIssue(
                severity="warning",
                message=(
                    f"target already has {target.record_count} records; "
                    "migrating into a non-empty collection"
                ),
            )
        )

    return CompatibilityReport(source=source, target=target, issues=issues)
