"""Report generation tests."""

from __future__ import annotations

import json

from vecparity.checkpoint import MigrationCheckpoint
from vecparity.report import report_to_dict, report_to_html, report_to_json
from vecparity.verify.parity import ParityReport, QueryResult


def _checkpoint() -> MigrationCheckpoint:
    return MigrationCheckpoint(
        migration_id="memory://a=>memory://b",
        source="memory://a",
        target="memory://b",
        status="cut_over",
        cursor=100.0,
        records_synced=10,
        records_deleted=2,
        last_verify_passed=True,
    )


def _parity(passing: bool) -> ParityReport:
    recall = 1.0 if passing else 0.0
    return ParityReport(
        results=[
            QueryResult(
                label="<script>alert(1)</script>",
                recall_at_k=recall,
                jaccard_overlap=recall,
                mean_score_drift=0.0,
                source_top_k=["a"],
                target_top_k=["a"] if passing else [],
            )
        ],
        min_recall_at_k=0.9,
    )


def test_report_to_dict_includes_migration_and_parity():
    d = report_to_dict(_checkpoint(), _parity(passing=True))

    assert d["migration"]["status"] == "cut_over"
    assert d["migration"]["records_synced"] == 10
    assert d["parity"]["results"][0]["recall_at_k"] == 1.0
    assert "generated_at" in d


def test_report_to_dict_handles_missing_pieces():
    d = report_to_dict(None, None)
    assert d["migration"] is None
    assert d["parity"] is None


def test_report_to_json_round_trips():
    text = report_to_json(_checkpoint(), _parity(passing=True))
    parsed = json.loads(text)
    assert parsed["migration"]["source"] == "memory://a"


def test_report_to_html_escapes_user_content():
    html = report_to_html(_checkpoint(), _parity(passing=False))

    assert "<script>alert(1)</script>" not in html  # would be a real XSS if unescaped
    assert "&lt;script&gt;" in html
    assert "FAIL" in html


def test_report_to_html_pass_badge():
    html = report_to_html(_checkpoint(), _parity(passing=True))
    assert "PASS" in html


def test_report_to_html_handles_no_migration_or_parity():
    html = report_to_html(None, None)
    assert "No migration state recorded" in html
    assert "No parity check recorded" in html
