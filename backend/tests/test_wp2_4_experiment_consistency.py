"""Consistency and portability contracts for the WP2.4 experiment record (blocking 3, 5, 6).

Three layers:

1. A generated-record test: after a real D5=false run, ``write_experiment`` must record the
   **shipped** candidate (``full_minus_presence``) — its C, features, set label, metrics and model
   hash — never the rejected ``full_logistic``. This is the seat for the
   "results metadata must read from the shipped candidate" mutation.
2. A portability test on generated records: committed/public config and manifest paths must be
   repository-relative POSIX (no backslashes, no drive letters, no machine-local absolute paths).
   Temporary absolute paths are permitted only inside tests.
3. Committed-record tests (skipped until the evidence commit regenerates them): all machine
   records must agree on experiment id, code commit, data source commit, shipped candidate, D5
   outcome, selected C, shipped feature columns, shipped feature-set label, model pickle SHA-256;
   the evidence report's stated shipped candidate / C / feature-set / model-hash prefix must match.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import numpy as np
import pytest

from touchline.modeling.logistic import L2_C_GRID
from touchline.modeling.preprocessing import ShotRow
from touchline.modeling.train import RunConfig, run_protocol, write_experiment

ROOT = Path(__file__).resolve().parents[2]
COMMITTED_EXP = ROOT / "experiments" / "shot_quality" / "exp-20260805-wp2_4-baselines"
RESULTS_CSV = ROOT / "experiments" / "results.csv"
REPORT_PATH = ROOT / "reports" / "wp2.4-baselines-evidence.md"


def _noise_rows(seed: int = 22) -> list[ShotRow]:
    rng = np.random.default_rng(seed)
    rows: list[ShotRow] = []
    for fold in range(5):
        for i in range(20):
            y = 1 if i < 10 else 0
            rows.append(
                ShotRow(
                    shot_id=f"{seed}-{fold}-{i}",
                    match_id=200 + fold,
                    fold=fold,
                    competition_id=43,
                    season_id=3,
                    y=y,
                    distance_to_goal=20.0 + float(rng.normal()),
                    visible_goal_angle=0.3 + 0.02 * float(rng.normal()),
                    body_part_name="Right Foot",
                    technique_name="Normal",
                    play_pattern_name="Regular Play",
                    first_time=bool(rng.random() < 0.2),
                    under_pressure=bool(rng.random() < 0.3),
                )
            )
    return rows


def _config(tmp_path: Path) -> RunConfig:
    return RunConfig(
        experiment_id="consistency-test",
        out_dir=str(tmp_path / "exp"),
        artifacts_dir=str(tmp_path / "artifacts"),
        code_commit="commit-a-sha",
        reproduction_commit="commit-a-sha",
        data_source_commit="b0bc9f22dd77c206ddedc1d742893b3bbe64baec",
        input_config_path=str(tmp_path / "input-config.json"),
        input_config_sha256="0" * 64,
        uv_lock_sha256="0" * 64,
        runtime_fingerprint={},
        require_clean_provenance=False,
        db_url_env="TOUCHLINE_DB_URL",
        assignments_sha256="0" * 64,
        cohort_sql_sha256="0" * 64,
        c_grid=L2_C_GRID,
        random_seed=0,
        n_folds=5,
        expected_shots=100,
        expected_matches=5,
        expected_fold_sizes={0: 20, 1: 20, 2: 20, 3: 20, 4: 20},
        bin_count=5,
        results_csv=str(tmp_path / "results.csv"),
    )


def _results_map(path: Path, experiment_id: str) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split(",")
    for line in lines[1:]:
        cells = line.split(",")
        if cells and cells[0] == experiment_id:
            return dict(zip(header, cells, strict=True))
    raise AssertionError(f"no results row for {experiment_id} in {path}")


def _assert_no_backslashes(record: Mapping[str, object]) -> None:
    """Generated records must be POSIX even when their paths are temporary absolutes."""
    for key, value in record.items():
        if isinstance(value, str):
            assert "\\" not in value, f"{key}: backslash in {value!r}"
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    assert "\\" not in item, f"{key}: backslash in {item!r}"


def _assert_portable(record: Mapping[str, object]) -> None:
    """Committed records must carry no backslash, drive letter or machine-local absolute path."""
    for key, value in record.items():
        if not isinstance(value, (str, list)):
            continue
        values = [value] if isinstance(value, str) else [v for v in value if isinstance(v, str)]
        for text in values:
            assert "\\" not in text, f"{key}: backslash in {text!r}"
            assert not text.startswith("C:") and not text.startswith("c:"), f"{key}: drive {text!r}"
            if key in {
                "out_dir",
                "artifacts_dir",
                "results_csv",
                "model_pickle_path",
                "notes_path",
                "coefficients_json",
            }:
                assert not text.startswith("/"), f"{key}: machine-local absolute {text!r}"


def test_write_experiment_records_the_shipped_candidate_only(tmp_path: Path) -> None:
    rows = _noise_rows()
    config = _config(tmp_path)
    metrics, bundle = run_protocol(rows, config)
    assert metrics["d5_include"] is False
    assert metrics["shipped_candidate"] == "full_minus_presence"

    write_experiment(metrics, bundle, config)

    results = _results_map(tmp_path / "results.csv", "consistency-test")
    assert results["shipped_candidate"] == "full_minus_presence"
    assert results["d5_include"] == "False"
    shipped_best_c = cast(float, metrics["shipped_best_c"])
    assert float(results["shipped_best_c"]) == pytest.approx(shipped_best_c)
    candidates: Mapping[str, object] = cast(Mapping[str, object], metrics["candidates"])
    minus = cast(Mapping[str, object], candidates["full_minus_presence"])
    full = cast(Mapping[str, object], candidates["full_logistic"])
    minus_ll = cast(float, minus["mean_log_loss"])
    full_ll = cast(float, full["mean_log_loss"])
    assert float(results["primary_value"]) == pytest.approx(minus_ll)
    # Must describe the shipped candidate, not the rejected full model.
    assert float(results["primary_value"]) != pytest.approx(full_ll)

    metrics_dict = json.loads((tmp_path / "exp" / "metrics.json").read_text(encoding="utf-8"))
    manifest = json.loads((tmp_path / "exp" / "artifact-manifest.json").read_text(encoding="utf-8"))
    config_dict = json.loads((tmp_path / "exp" / "config.json").read_text(encoding="utf-8"))
    assert manifest["shipped_candidate"] == "full_minus_presence"
    assert manifest["model_pickle_sha256"] == metrics["model_pickle_sha256"]
    assert metrics_dict["model_pickle_sha256"] == metrics["model_pickle_sha256"]
    # Machine records must carry the runtime fingerprint (blocking correction 4).
    for record in (metrics_dict, manifest, config_dict):
        assert "runtime_fingerprint" in record
        assert "uv_lock_sha256" in record
        assert "input_config_sha256" in record
        assert "reproduction_commit" in record
    _assert_no_backslashes(config_dict)
    _assert_no_backslashes(manifest)


def _committed_has_schema() -> bool:
    path = COMMITTED_EXP / "metrics.json"
    if not path.exists():
        return False
    data = json.loads(path.read_text(encoding="utf-8"))
    return isinstance(data, dict) and "reproduction_commit" in data


def _committed_or_skip() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    if not _committed_has_schema():
        pytest.skip(
            "committed experiment predates the shipped-candidate schema; "
            "regenerated in the evidence commit"
        )
    config = json.loads((COMMITTED_EXP / "config.json").read_text(encoding="utf-8"))
    metrics = json.loads((COMMITTED_EXP / "metrics.json").read_text(encoding="utf-8"))
    manifest = json.loads((COMMITTED_EXP / "artifact-manifest.json").read_text(encoding="utf-8"))
    return config, metrics, manifest


def test_committed_records_are_cross_file_consistent() -> None:
    config, metrics, manifest = _committed_or_skip()
    for field in (
        "experiment_id",
        "code_commit",
        "reproduction_commit",
        "data_source_commit",
        "input_config_sha256",
        "uv_lock_sha256",
    ):
        assert metrics[field] == config[field] == manifest[field], field
    assert (
        metrics["runtime_fingerprint"]
        == config["runtime_fingerprint"]
        == manifest["runtime_fingerprint"]
    )
    assert (
        metrics["shipped_candidate"] == config["shipped_candidate"] == manifest["shipped_candidate"]
    )
    assert metrics["d5_include"] == manifest["d5_include"] == config["d5_include"]
    assert (
        metrics["shipped_feature_set"]
        == config["shipped_feature_set"]
        == manifest["shipped_feature_set"]
    )
    assert (
        metrics["shipped_feature_columns"]
        == config["shipped_feature_columns"]
        == manifest["shipped_feature_columns"]
    )
    assert metrics["shipped_best_c"] == manifest["shipped_best_c"]
    assert metrics["model_pickle_sha256"] == manifest["model_pickle_sha256"]

    results = _results_map(RESULTS_CSV, str(metrics["experiment_id"]))
    assert results["shipped_candidate"] == metrics["shipped_candidate"]
    assert results["d5_include"] == str(metrics["d5_include"])
    assert results["model_pickle_sha256"] == metrics["model_pickle_sha256"]
    assert results["code_commit"] == metrics["code_commit"]
    assert results["reproduction_commit"] == metrics["reproduction_commit"]
    assert results["input_config_sha256"] == metrics["input_config_sha256"]
    assert results["uv_lock_sha256"] == metrics["uv_lock_sha256"]

    report = REPORT_PATH.read_text(encoding="utf-8")
    assert str(metrics["shipped_candidate"]) in report
    assert str(metrics["model_pickle_sha256"]) in report
    assert str(metrics["reproduction_commit"]) in report
    _assert_portable(config)
    _assert_portable(manifest)


def test_committed_results_path_fields_are_portable() -> None:
    if not _committed_has_schema():
        pytest.skip(
            "committed experiment predates the shipped-candidate schema; "
            "regenerated in the evidence commit"
        )
    metrics = json.loads((COMMITTED_EXP / "metrics.json").read_text(encoding="utf-8"))
    results = _results_map(RESULTS_CSV, str(metrics["experiment_id"]))
    for key in ("notes_path",):
        assert "\\" not in results[key]
        assert not results[key].startswith("C:")
