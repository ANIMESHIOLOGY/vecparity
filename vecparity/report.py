"""Rich migration report generation: a self-contained HTML page and a
JSON export, combining a migration's checkpoint state with its parity
results. No external assets, works offline.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from typing import Any

from vecparity.checkpoint import MigrationCheckpoint
from vecparity.verify.parity import ParityReport


def _checkpoint_dict(cp: MigrationCheckpoint | None) -> dict[str, Any] | None:
    if cp is None:
        return None
    return {
        "migration_id": cp.migration_id,
        "source": cp.source,
        "target": cp.target,
        "status": cp.status,
        "cursor": cp.cursor,
        "records_synced": cp.records_synced,
        "records_deleted": cp.records_deleted,
        "last_verify_passed": cp.last_verify_passed,
        "last_batch_at": cp.last_batch_at,
    }


def report_to_dict(
    checkpoint: MigrationCheckpoint | None, parity: ParityReport | None
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "migration": _checkpoint_dict(checkpoint),
        "parity": None if parity is None else parity.model_dump(),
    }


def report_to_json(checkpoint: MigrationCheckpoint | None, parity: ParityReport | None) -> str:
    return json.dumps(report_to_dict(checkpoint, parity), indent=2)


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>vecparity migration report</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif;
         max-width: 900px; margin: 2rem auto; padding: 0 1rem; color: #1a1a2e; }}
  h1 {{ font-size: 1.4rem; }}
  h2 {{ font-size: 1.1rem; margin-top: 2rem; border-bottom: 1px solid #ddd; padding-bottom: 0.3rem; }}
  .meta {{ color: #666; font-size: 0.85rem; }}
  .cards {{ display: flex; flex-wrap: wrap; gap: 0.75rem; margin: 1rem 0; }}
  .card {{ background: #f5f5fa; border-radius: 8px; padding: 0.75rem 1rem; min-width: 140px; }}
  .card .label {{ font-size: 0.75rem; color: #666; text-transform: uppercase; }}
  .card .value {{ font-size: 1.3rem; font-weight: 600; }}
  .badge {{ display: inline-block; padding: 0.15rem 0.6rem; border-radius: 999px;
            font-size: 0.8rem; font-weight: 600; }}
  .badge.pass {{ background: #d4f4dd; color: #1a7a3a; }}
  .badge.fail {{ background: #fbdada; color: #a3212e; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 0.5rem; font-size: 0.9rem; }}
  th, td {{ text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #eee; }}
  th {{ color: #666; font-weight: 600; font-size: 0.8rem; text-transform: uppercase; }}
</style>
</head>
<body>
<h1>vecparity migration report</h1>
<p class="meta">Generated {generated_at}</p>
{migration_section}
{parity_section}
</body>
</html>
"""


def _migration_section(cp: MigrationCheckpoint | None) -> str:
    if cp is None:
        return "<h2>Migration</h2><p>No migration state recorded.</p>"
    return f"""<h2>Migration</h2>
<div class="cards">
  <div class="card"><div class="label">Source</div><div class="value">{html.escape(cp.source)}</div></div>
  <div class="card"><div class="label">Target</div><div class="value">{html.escape(cp.target)}</div></div>
  <div class="card"><div class="label">Status</div><div class="value">{html.escape(cp.status)}</div></div>
  <div class="card"><div class="label">Records synced</div><div class="value">{cp.records_synced}</div></div>
  <div class="card"><div class="label">Records deleted</div><div class="value">{cp.records_deleted}</div></div>
</div>"""


def _parity_section(report: ParityReport | None) -> str:
    if report is None:
        return "<h2>Parity</h2><p>No parity check recorded.</p>"
    badge_class = "pass" if report.passed else "fail"
    badge_text = "PASS" if report.passed else "FAIL"
    rows = "\n".join(
        f"<tr><td>{html.escape(r.label or '(unlabeled)')}</td><td>{r.recall_at_k:.3f}</td>"
        f"<td>{r.jaccard_overlap:.3f}</td><td>{r.mean_score_drift:.4f}</td></tr>"
        for r in report.results
    )
    return f"""<h2>Parity <span class="badge {badge_class}">{badge_text}</span></h2>
<div class="cards">
  <div class="card"><div class="label">Mean recall@k</div><div class="value">{report.mean_recall_at_k:.3f}</div></div>
  <div class="card"><div class="label">p50 recall</div><div class="value">{report.p50_recall:.3f}</div></div>
  <div class="card"><div class="label">p95 recall</div><div class="value">{report.p95_recall:.3f}</div></div>
  <div class="card"><div class="label">Min recall</div><div class="value">{report.min_recall:.3f}</div></div>
  <div class="card"><div class="label">Below threshold</div><div class="value">{report.queries_below_threshold_pct:.1f}%</div></div>
</div>
<table>
  <thead><tr><th>Query</th><th>Recall@k</th><th>Overlap</th><th>Score Drift</th></tr></thead>
  <tbody>
{rows}
  </tbody>
</table>"""


def report_to_html(checkpoint: MigrationCheckpoint | None, parity: ParityReport | None) -> str:
    return _HTML_TEMPLATE.format(
        generated_at=datetime.now(timezone.utc).isoformat(),
        migration_section=_migration_section(checkpoint),
        parity_section=_parity_section(parity),
    )
