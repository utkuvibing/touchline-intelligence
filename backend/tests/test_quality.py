"""Public contracts for the independent WP1.4 quality reporting seam."""

from __future__ import annotations

import json
from pathlib import Path

from touchline.quality import PERSISTED_GRAINS, QualityReport, render_text

ROOT = Path(__file__).resolve().parents[2]


def test_report_serialization_is_deterministic_and_separates_result_classes() -> None:
    """Machine and human reports retain errors, warnings, coverage and limitations separately."""
    report = QualityReport(
        scope=((43, 106),),
        source_commit="b0bc9f22dd77c206ddedc1d742893b3bbe64baec",
        manifest_run_id="00000000-0000-0000-0000-000000000001",
        source_counts={name: 9 for name in PERSISTED_GRAINS},
        database_counts={name: 9 for name in PERSISTED_GRAINS},
        invariant_violations={"provider_xg_in_residual_json": 0},
        errors=(),
        warnings=("event coordinate exception: 120.1 accepted",),
        coverage={"shots_without_location": 1},
        exclusions={"provider_xg": "not persisted by design"},
        limitations=("Position intervals are preserved without inferred chronology.",),
        db_execution_status="executed",
    )

    payload = json.loads(report.to_json())
    assert list(payload) == sorted(payload)
    assert payload["errors"] == []
    assert payload["attribution"] == "Data provided by StatsBomb."
    assert payload["coverage"] == {"shots_without_location": 1}
    text = render_text(report)
    assert "Errors\n  none" in text
    assert "Reconciliation (source, database, status)" in text
    assert "events: 9, 9, OK" in text
    assert "Invariant violations (count, status)" in text
    assert "provider_xg_in_residual_json: 0, OK" in text
    assert "Known limitations" in text
    assert "Data provided by StatsBomb." in text


def test_committed_sampling_checklist_carries_statsbomb_attribution() -> None:
    """The separately published manual checklist retains the licence attribution."""
    checklist = (ROOT / "reports" / "wp1.4-sampling-checklist.md").read_text(encoding="utf-8")

    assert checklist.splitlines()[-1] == "Data provided by StatsBomb."
    assert checklist.count("Data provided by StatsBomb.") == 1
