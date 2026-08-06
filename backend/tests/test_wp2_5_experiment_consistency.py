"""Cross-record consistency and the publication boundary for the committed WP2.5 packet.

Four machine records and one prose report describe the same run. If they disagree, at least one of
them is lying to a reader, and the packet is the only thing a reviewer outside this machine can
see. These tests never skip: the packet is committed, so a missing or stale record is a failure.

The publication boundary is enforced too. `docs/` is deliberately unpublished, so a committed
record that points a reader there sends them somewhere they cannot go — a defect WP2.4 shipped once
and caught only after adding a test that actually read the generated notes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "experiments" / "shot_quality" / "exp-20260806-wp2_5-gradient-boosting"
RESULTS_CSV = ROOT / "experiments" / "results.csv"
REPORT = ROOT / "reports" / "wp2.5-gradient-boosting-evidence.md"
WP24 = ROOT / "experiments" / "shot_quality" / "exp-20260805-wp2_4-baselines"
EXPERIMENT_ID = "exp-20260806-wp2_5-gradient-boosting"

#: Repository-internal trees the publication policy keeps out of the published repository.
UNPUBLISHED = ("docs/", "docs\\", "AGENTS.md", ".scratch/")


def _load(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((EXP / name).read_text(encoding="utf-8"))
    return payload


def _results_row(experiment_id: str) -> dict[str, str]:
    lines = RESULTS_CSV.read_text(encoding="utf-8").splitlines()
    header = lines[0].split(",")
    for line in lines[1:]:
        cells = line.split(",")
        if cells and cells[0] == experiment_id:
            return dict(zip(header, cells, strict=True))
    raise AssertionError(f"no results row for {experiment_id}")


def _assert_portable(record: Mapping[str, Any], where: str) -> None:
    for key, value in record.items():
        texts = [value] if isinstance(value, str) else []
        if isinstance(value, list):
            texts = [v for v in value if isinstance(v, str)]
        for text in texts:
            assert "\\" not in text, f"{where}.{key}: backslash in {text!r}"
            assert not text.lower().startswith("c:"), f"{where}.{key}: drive letter in {text!r}"


def test_the_machine_records_agree_on_identity_and_provenance() -> None:
    metrics, config, manifest = (
        _load("metrics.json"),
        _load("config.json"),
        _load("artifact-manifest.json"),
    )
    for field in (
        "experiment_id",
        "code_commit",
        "reproduction_commit",
        "data_source_commit",
        "input_config_sha256",
        "uv_lock_sha256",
    ):
        assert metrics[field] == config[field] == manifest[field], field
    assert metrics["runtime_fingerprint"] == config["runtime_fingerprint"]
    assert metrics["runtime_fingerprint"] == manifest["runtime_fingerprint"]
    assert metrics["model_pickle_sha256"] == manifest["model_pickle_sha256"]


def test_the_records_agree_on_the_two_distinct_outcomes() -> None:
    """``artifact_candidate`` is what was built, ``shipped_candidate`` what won. Both recorded."""
    metrics, config, manifest = (
        _load("metrics.json"),
        _load("config.json"),
        _load("artifact-manifest.json"),
    )
    assert metrics["artifact_candidate"] == config["artifact_candidate"] == "hist_gbm"
    assert manifest["artifact_candidate"] == "hist_gbm"
    for record in (metrics, config, manifest):
        assert record["shipped_candidate"] == metrics["shipped_candidate"]
        assert record["shipped_feature_set"] == "geometry+categoricals"
    assert metrics["shipped_candidate"] == metrics["replacement_chain_b"]["selection_incumbent"]
    assert metrics["protocol_incumbent"] == metrics["replacement_chain_a"]["protocol_incumbent"]
    assert metrics["gbm_selected_hyperparameters"] == config["gbm_selected_hyperparameters"]
    assert metrics["gbm_selected_hyperparameters"] == manifest["gbm_selected_hyperparameters"]


def test_the_results_row_describes_the_boosting_artifact_not_the_winner() -> None:
    """Regression against a row whose model label and hash disagreed with its own metrics."""
    metrics = _load("metrics.json")
    row = _results_row(EXPERIMENT_ID)
    booster = metrics["candidates"]["hist_gbm"]
    assert row["model"] == "hist-gradient-boosting"
    assert row["model_pickle_sha256"] == metrics["model_pickle_sha256"]
    # The results index carries full float precision while the canonical JSON rounds to twelve
    # decimals (inherited WP2.4 behaviour), so the comparison is made at the record's precision.
    assert round(float(row["primary_value"]), 12) == booster["mean_log_loss"]
    assert round(float(row["brier"]), 12) == booster["pooled_oof"]["brier"]
    assert round(float(row["log_loss"]), 12) == booster["pooled_oof"]["log_loss"]
    # ...and demonstrably not the winner's numbers, which is the defect this guards.
    winner = metrics["candidates"][metrics["shipped_candidate"]]
    assert round(float(row["primary_value"]), 12) != winner["mean_log_loss"]
    # The selection outcome lives in its own column and may disagree, which is the point.
    assert row["shipped_candidate"] == metrics["shipped_candidate"]
    assert row["protocol_incumbent"] == metrics["protocol_incumbent"]
    assert row["d5_include"] == "n/a" and row["shipped_best_c"] == "n/a"
    assert row["query_hash"] == metrics["cohort_sql_sha256"]


def test_the_wp2_4_row_and_record_were_left_untouched() -> None:
    """WP2.5 appends. It must not have rewritten a closed work package's published row."""
    wp24 = json.loads((WP24 / "metrics.json").read_text(encoding="utf-8"))
    row = _results_row("exp-20260805-wp2_4-baselines")
    assert row["model"] == "regularized-logistic"
    assert row["model_pickle_sha256"] == wp24["model_pickle_sha256"]
    assert row["shipped_candidate"] == wp24["shipped_candidate"]
    assert row["d5_include"] == str(wp24["d5_include"])


def test_the_wp2_4_candidates_were_reproduced_to_twelve_decimals() -> None:
    """The comparison is only meaningful if the incumbents reproduce on these exact rows."""
    new = _load("metrics.json")["candidates"]
    old = json.loads((WP24 / "metrics.json").read_text(encoding="utf-8"))["candidates"]
    for key in ("constant", "geometry_logistic", "full_logistic", "full_minus_presence"):
        a, b = old[key], new[key]
        for field in (
            "mean_log_loss",
            "sd_log_loss_ddof0",
            "max_abs_deviation_supported",
            "supported_bins",
        ):
            assert a[field] == b[field], f"{key}.{field}"
        assert a["pooled_oof"] == b["pooled_oof"], key
        assert a["per_fold"] == b["per_fold"], key
        assert a["reliability"] == b["reliability"], key
        assert a.get("best_c") == b.get("best_c"), key


def test_the_determinism_pin_is_recorded_in_the_run() -> None:
    fingerprint = _load("metrics.json")["runtime_fingerprint"]
    assert fingerprint["omp_num_threads"] == "1"
    assert fingerprint["threadpool_num_threads"] == [1]
    assert _load("metrics.json")["thread_limit"] == 1


def test_committed_records_are_portable_and_stay_inside_the_publication() -> None:
    for name in ("metrics.json", "config.json", "artifact-manifest.json"):
        _assert_portable(_load(name), name)
    notes = (EXP / "notes.md").read_text(encoding="utf-8")
    assert "\\" not in notes
    for reference in UNPUBLISHED:
        assert reference not in notes, f"notes point a reader at unpublished {reference!r}"
        assert reference not in REPORT.read_text(encoding="utf-8"), (
            f"the evidence report points a reader at unpublished {reference!r}"
        )
    assert REPORT.read_text(encoding="utf-8").rstrip().endswith("Data provided by StatsBomb.")


def test_the_report_states_the_measured_outcome_and_the_selected_grid_point() -> None:
    metrics = _load("metrics.json")
    report = REPORT.read_text(encoding="utf-8")
    assert metrics["shipped_candidate"] in report
    assert metrics["code_commit"] in report
    selected = metrics["gbm_selected_hyperparameters"]
    assert str(selected["learning_rate"]) in report
    assert f"{metrics['candidates']['hist_gbm']['mean_log_loss']:.6f}" in report
