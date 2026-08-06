"""End-to-end WP2.5 dry run against a seeded synthetic schema.

The unit suite proves the protocol arithmetic and the full-cohort suite proves the real population.
Neither exercises the path in between: config on disk, artifacts verified, a real database read
through the loader, the protocol, and a complete experiment record written to disk. This does, on a
throwaway schema with the shared synthetic cohort, so a wiring break between those stages cannot
hide behind two green suites either side of it.

Requires ``TOUCHLINE_DB_URL``; skipped otherwise. Everything it writes goes to ``tmp_path``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from support.db_safety import connect_local
from support.wp24_synthetic import EXPECTED_FOLDS, EXPECTED_MATCHES, EXPECTED_SHOTS, seed_cohort

from touchline.boosting_bootstrap import OMP_ENV_VAR, OMP_THREAD_PIN
from touchline.modeling.artifact import load_boosting_bundle
from touchline.modeling.boosting import GBM_GRID
from touchline.modeling.train_boosting import main

DB_URL = os.environ.get("TOUCHLINE_DB_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(DB_URL is None, reason="TOUCHLINE_DB_URL is not set"),
]

TEST_SCHEMA = "wp25_dry_run_test"
ROOT = Path(__file__).resolve().parents[2]

#: Four development matches from the shared synthetic cohort, plus one calibration and one holdout
#: match that exist in the database and must never reach the fitted input.
SYN_ASSIGNMENTS = """match_id,competition_id,season_id,match_date,split,fold
200,43,3,2018-06-14,development,0
201,43,3,2018-06-15,development,1
202,43,3,2018-06-16,development,2
203,43,3,2018-06-17,development,3
204,43,3,2018-06-18,development,4
205,43,3,2018-06-19,development,0
206,43,3,2018-06-20,development,1
207,43,3,2018-06-21,development,2
208,43,3,2018-06-22,development,3
209,43,3,2018-06-23,development,4
230,43,106,2022-11-21,calibration,
240,55,282,2024-06-14,holdout,
"""


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    with connect_local(DB_URL) as connection:
        with connection.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE')
            cur.execute(f'CREATE SCHEMA "{TEST_SCHEMA}"')
            cur.execute(f'SET search_path TO "{TEST_SCHEMA}"')
        connection.commit()
        try:
            yield connection
        finally:
            connection.rollback()
            with connection.cursor() as cur:
                cur.execute(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE')
            connection.commit()


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    import hashlib

    assignments = tmp_path / "assignments.csv"
    assignments.write_bytes(SYN_ASSIGNMENTS.encode("utf-8"))
    cohort_sql = ROOT / "backend" / "sql" / "wp2_1" / "01_model_shot_cohort.sql"
    config = {
        "experiment_id": "exp-dry-run-wp2_5",
        "out_dir": str(tmp_path / "exp"),
        "artifacts_dir": str(tmp_path / "art"),
        "data_source_commit": "b0bc9f22dd77c206ddedc1d742893b3bbe64baec",
        "db_url_env": "TOUCHLINE_DB_URL",
        "assignments_sha256": hashlib.sha256(assignments.read_bytes()).hexdigest(),
        "cohort_sql_sha256": hashlib.sha256(cohort_sql.read_bytes()).hexdigest(),
        "model_family": "hist-gradient-boosting",
        "c_grid": [0.01, 0.1, 1.0, 10.0],
        "gbm_grid": [point.as_dict() for point in GBM_GRID],
        "random_seed": 0,
        "n_folds": 5,
        "expected_shots": EXPECTED_SHOTS,
        "expected_matches": EXPECTED_MATCHES,
        "expected_fold_sizes": {str(k): v for k, v in EXPECTED_FOLDS.items()},
        "bin_count": 5,
        "results_csv": str(tmp_path / "results.csv"),
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path, assignments, cohort_sql


def test_a_dry_run_writes_a_complete_and_self_consistent_record(
    conn: psycopg.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_cohort(conn)
    config_path, assignments, cohort_sql = _write_inputs(tmp_path)
    monkeypatch.setenv("TOUCHLINE_TRAIN_SCHEMA", TEST_SCHEMA)
    # The trainer refuses unless the launcher pinned the process; the launcher is exercised by the
    # subprocess suite, so here the pinned environment is supplied directly.
    monkeypatch.setenv(OMP_ENV_VAR, OMP_THREAD_PIN)

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--assignments-csv",
            str(assignments),
            "--cohort-sql",
            str(cohort_sql),
            "--code-commit",
            "dry-run-commit",
        ]
    )
    assert exit_code == 0

    out = tmp_path / "exp"
    for name in ("metrics.json", "config.json", "notes.md", "artifact-manifest.json"):
        assert (out / name).is_file(), name
    metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    manifest = json.loads((out / "artifact-manifest.json").read_text(encoding="utf-8"))

    assert metrics["n_rows"] == EXPECTED_SHOTS
    assert metrics["n_matches"] == EXPECTED_MATCHES
    assert sorted(metrics["candidates"]) == [
        "constant",
        "full_logistic",
        "full_minus_presence",
        "geometry_logistic",
        "hist_gbm",
    ]
    assert metrics["artifact_candidate"] == "hist_gbm"
    assert metrics["shipped_candidate"] == metrics["replacement_chain_b"]["selection_incumbent"]

    # The bundle on disk agrees with the record about both meanings.
    bundle = load_boosting_bundle(tmp_path / "art" / "model.pkl")
    assert bundle.artifact_candidate == metrics["artifact_candidate"]
    assert bundle.selection_incumbent == metrics["shipped_candidate"]
    assert manifest["bundle_artifact_candidate"] == bundle.artifact_candidate
    assert manifest["bundle_selection_incumbent"] == bundle.selection_incumbent

    # Exactly one results row, describing the boosting artifact.
    rows = [
        line
        for line in (tmp_path / "results.csv").read_text(encoding="utf-8").splitlines()[1:]
        if line.strip()
    ]
    assert len([r for r in rows if r.split(",")[0] == "exp-dry-run-wp2_5"]) == 1
    assert "hist-gradient-boosting" in rows[0]


def test_the_run_refuses_when_the_process_is_not_pinned(
    conn: psycopg.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D20 is a process contract, so the trainer checks it rather than trusting the caller."""
    seed_cohort(conn)
    config_path, assignments, cohort_sql = _write_inputs(tmp_path)
    monkeypatch.setenv("TOUCHLINE_TRAIN_SCHEMA", TEST_SCHEMA)
    monkeypatch.setenv(OMP_ENV_VAR, "8")

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--assignments-csv",
                str(assignments),
                "--cohort-sql",
                str(cohort_sql),
                "--code-commit",
                "dry-run-commit",
            ]
        )
        == 1
    )
    assert not (tmp_path / "exp").exists()
