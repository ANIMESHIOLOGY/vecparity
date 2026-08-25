"""Schema inspection and compatibility tests, using the in-memory adapter."""

from __future__ import annotations

from vecparity.adapters.memory import MemoryAdapter
from vecparity.schema import compare_schemas, inspect_adapter
from vecparity.types import VectorRecord


def test_inspect_adapter_infers_dimension_and_field_types():
    adapter = MemoryAdapter()
    adapter.upsert(
        [
            VectorRecord(id="a", vector=[1.0, 2.0, 3.0], metadata={"tag": "x", "score": 1}),
            VectorRecord(id="b", vector=[4.0, 5.0, 6.0], metadata={"tag": "y", "score": 2}),
        ]
    )

    schema = inspect_adapter(adapter, sample_size=10)

    assert schema.record_count == 2
    assert schema.dimension == 3
    assert schema.metadata_field_types == {"tag": "str", "score": "int"}
    assert schema.sample_size == 2


def test_inspect_adapter_on_empty_collection():
    schema = inspect_adapter(MemoryAdapter())
    assert schema.record_count == 0
    assert schema.dimension is None
    assert schema.sample_size == 0


def test_inspect_adapter_respects_sample_size():
    adapter = MemoryAdapter()
    adapter.upsert([VectorRecord(id=f"d{i}", vector=[float(i)]) for i in range(50)])

    schema = inspect_adapter(adapter, sample_size=5)

    assert schema.sample_size == 5
    assert schema.record_count == 50  # count() isn't limited by the sample


def test_compare_schemas_flags_dimension_mismatch():
    source = inspect_adapter(_seeded([1.0, 2.0]))
    target = inspect_adapter(_seeded([1.0, 2.0, 3.0]))

    report = compare_schemas(source, target)

    assert report.blocking
    assert any("dimension mismatch" in i.message for i in report.issues)


def test_compare_schemas_flags_metadata_type_drift_as_warning_only():
    source = inspect_adapter(_seeded([1.0], metadata={"tag": "x"}))
    target = inspect_adapter(_seeded([1.0], metadata={"tag": 1}))

    report = compare_schemas(source, target)

    assert not report.blocking
    assert any("tag" in i.message and i.severity == "warning" for i in report.issues)


def test_compare_schemas_warns_on_nonempty_target():
    source = inspect_adapter(_seeded([1.0]))
    target = inspect_adapter(_seeded([1.0]))

    report = compare_schemas(source, target)

    assert not report.blocking
    assert any("already has" in i.message for i in report.issues)


def _seeded(vector: list[float], metadata: dict | None = None) -> MemoryAdapter:
    adapter = MemoryAdapter()
    adapter.upsert([VectorRecord(id="a", vector=vector, metadata=metadata or {})])
    return adapter
