"""Immutable-artifact checks for the post-holdout WP2.7 closeout.

These tests read only aggregate JSON, generated presentation files, and recorded evidence hashes.
They never open a database or load Euro2024 rows.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "experiments/shot_quality/exp-20260809-wp2_7-calibration-holdout"
AUDIT = OUTPUT / "holdout-access-audit.json"
DECISION = OUTPUT / "calibration-decision.json"
METRICS = OUTPUT / "holdout-metrics.json"
RECORD = OUTPUT / "experiment-record.json"

EXPECTED_DECISION_SHA256 = "f5c9ccf665924069f755fbd669d4a9abada1e5791e957d3d436d42d500277e89"
EXPECTED_STAGES = [
    "holdout_open",
    "membership_asserted",
    "scored",
    "bootstrap",
    "slices",
    "evidence_written",
    "holdout_closed",
    "experiment_record_written",
    "audit_finalized",
]


def _load(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_completed_audit_matches_immutable_aggregate_contract() -> None:
    audit = _load(AUDIT)
    decision_envelope = _load(DECISION)
    metrics = _load(METRICS)
    record = _load(RECORD)

    assert decision_envelope["decision_sha256"] == EXPECTED_DECISION_SHA256
    assert audit["decision_sha256"] == EXPECTED_DECISION_SHA256
    assert metrics["decision_sha256"] == EXPECTED_DECISION_SHA256
    assert record["decision_sha256"] == EXPECTED_DECISION_SHA256
    assert audit["holdout_open_count"] == 1
    assert {
        key: audit[key] for key in ("n_rows", "n_matches", "n_goals", "n_misses")
    } == {"n_rows": 1304, "n_matches": 51, "n_goals": 98, "n_misses": 1206}
    assert audit["stages"] == EXPECTED_STAGES
    assert record["aggregate_counts"] == {
        "rows": 1304,
        "matches": 51,
        "goals": 98,
        "misses": 1206,
    }

    for relative_path, expected_sha256 in audit["evidence_files_sha256"].items():
        path = ROOT / relative_path
        assert path.exists(), relative_path
        assert _sha256(path) == expected_sha256, relative_path


def test_legacy_raw_anchor_field_is_calibration_context_not_holdout_rows() -> None:
    decision = _load(DECISION)["decision"]
    metrics = _load(METRICS)
    calibration_anchor = decision["raw_anchor_reliability"]
    legacy_anchor = metrics["raw_anchor_reliability"]

    assert len(legacy_anchor) == len(calibration_anchor) == 5
    for measured, source in zip(legacy_anchor, calibration_anchor, strict=True):
        assert measured["bin"] == source["bin"]
        assert measured["count"] == source["count"]
        assert measured["positive_count"] == source["positive_count"]
        for key in (
            "lower",
            "upper",
            "raw_mean_prediction",
            "calibrated_mean_prediction",
            "observed_rate",
        ):
            assert measured[key] == pytest.approx(round(float(source[key]), 12))
    assert sum(row["count"] for row in legacy_anchor) == 1430
    assert metrics["variants"]["raw"]["n"] == 1304
    assert metrics["variants"]["calibrated"]["n"] == 1304
    assert metrics["variants"]["raw"]["reliability"] != legacy_anchor
    assert metrics["variants"]["calibrated"]["reliability"] != legacy_anchor


def test_closeout_reports_use_only_recorded_aggregate_values() -> None:
    report = (ROOT / "reports/wp2.7-calibration-holdout-closeout.md").read_text(
        encoding="utf-8"
    )
    model_card = (ROOT / "reports/wp2.7-model-card-closeout.md").read_text(encoding="utf-8")
    clarification = (ROOT / "reports/wp2.7-holdout-schema-clarification.md").read_text(
        encoding="utf-8"
    )
    combined = "\n".join((report, model_card, clarification))
    normalized = " ".join(combined.split())
    for value in (
        "1,304",
        "51",
        "98",
        "1,206",
        "0.239307508271",
        "0.243112806225",
        "0.064707399225",
        "0.066029980705",
        "0.744677970691",
        "0.223985679737",
        "[0.000095442006, 0.007815706219]",
        "[-0.000013107008, 0.002806020149]",
        "calibration_raw_anchor_reliability",
        "Data provided by StatsBomb.",
        "the WC2022-fitted Platt transform did not improve out-of-tournament probability quality",
        "calibration transport across tournaments is not established",
    ):
        assert value in normalized, value
    candidate_section = model_card.split("## Calibration protocol and decision", maxsplit=1)[0]
    for value in (
        "`constant`",
        "`geometry_logistic`",
        "`full_logistic`",
        "`full_minus_presence`",
        "`hist_gbm`",
        "`pytorch_mlp`",
        "candidate_replaces_incumbent=false",
        "distance_to_goal",
        "visible_goal_angle",
        "body_part_name::",
        "technique_name::",
        "play_pattern_name::",
        "`shot_type_name` is not a shipped feature column",
    ):
        assert value in candidate_section, value
    assert "pre-holdout adopted variant" in combined.lower()
    assert "did not reselect" in combined.lower() or "without selecting" in combined.lower()


def test_generated_model_card_heading_is_utf8_em_dash_not_terminal_mojibake() -> None:
    for path in (
        ROOT / "reports/wp2.7-model-card.md",
        OUTPUT / "model-card.md",
    ):
        text = path.read_text(encoding="utf-8")
        assert "—" in text.splitlines()[0]
        assert "â€”" not in text
