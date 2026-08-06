"""A persisted WP2.5 bundle must load and score in a **different** process.

The in-process round-trip in ``test_wp2_5_artifact.py`` cannot see the failure this guards against:
a pickle whose class identity resolves only in the interpreter that wrote it. That is why WP2.4
pinned ``__module__`` explicitly, and the same pin has to be proved for the boosting bundle by
actually leaving the process.

The bundle is produced by a real training run against a seeded synthetic schema, then loaded and
scored by a fresh interpreter that imports nothing from this test and never sees the training code
path. Requires ``TOUCHLINE_DB_URL``; skipped otherwise.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from support.db_safety import connect_local
from support.wp24_synthetic import EXPECTED_FOLDS, EXPECTED_MATCHES, EXPECTED_SHOTS, seed_cohort

from touchline.boosting_bootstrap import OMP_ENV_VAR, OMP_THREAD_PIN
from touchline.modeling.boosting import GBM_GRID
from touchline.modeling.train_boosting import main

DB_URL = os.environ.get("TOUCHLINE_DB_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(DB_URL is None, reason="TOUCHLINE_DB_URL is not set"),
]

TEST_SCHEMA = "wp25_crossprocess_test"
ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "backend" / "src"

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

#: Loads the persisted bundle and scores rows built from scratch. It imports only the public
#: artifact API — never the trainer — so a class identity that resolves only under the writing
#: process would fail here.
CONSUMER = """
import hashlib, json, sys
import numpy as np
from touchline.modeling.artifact import load_boosting_bundle, infer_boosting
from touchline.modeling.preprocessing import ShotRow

bundle = load_boosting_bundle(sys.argv[1])
rows = [
    ShotRow(shot_id="q%d" % i, match_id=200, fold=None, competition_id=43, season_id=3, y=0,
            distance_to_goal=8.0 + 0.75 * i, visible_goal_angle=0.45 - 0.01 * i,
            body_part_name="Right Foot", technique_name="Normal",
            play_pattern_name="Regular Play", first_time=None, under_pressure=None)
    for i in range(12)
]
p = infer_boosting(bundle, rows)
print(json.dumps({
    "class_module": type(bundle).__module__,
    "class_name": type(bundle).__qualname__,
    "schema_version": bundle.schema_version,
    "artifact_candidate": bundle.artifact_candidate,
    "selection_incumbent": bundle.selection_incumbent,
    "n_features": len(bundle.selected_columns),
    "predictions_sha": hashlib.sha256(np.ascontiguousarray(p).tobytes()).hexdigest(),
    "in_unit_interval": bool(np.all(p >= 0.0) and np.all(p <= 1.0)),
}))
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


def test_a_persisted_bundle_loads_and_scores_in_a_fresh_interpreter(
    conn: psycopg.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_cohort(conn)
    assignments = tmp_path / "assignments.csv"
    assignments.write_bytes(SYN_ASSIGNMENTS.encode("utf-8"))
    cohort_sql = ROOT / "backend" / "sql" / "wp2_1" / "01_model_shot_cohort.sql"
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "experiment_id": "exp-crossprocess-wp2_5",
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
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TOUCHLINE_TRAIN_SCHEMA", TEST_SCHEMA)
    monkeypatch.setenv(OMP_ENV_VAR, OMP_THREAD_PIN)
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
                "crossprocess-commit",
            ]
        )
        == 0
    )

    pkl = tmp_path / "art" / "model.pkl"
    manifest = json.loads((tmp_path / "exp" / "artifact-manifest.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(pkl.read_bytes()).hexdigest() == manifest["model_pickle_sha256"]

    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    result = subprocess.run(
        [sys.executable, "-c", CONSUMER, str(pkl)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)

    # The persisted class identity resolves outside the writing process.
    assert payload["class_module"] == "touchline.modeling.artifact"
    assert payload["class_name"] == "BoostingBundle"
    assert payload["schema_version"] == manifest["boosting_artifact_schema_version"]
    # ...and the two identity fields survive serialization with their distinct meanings intact.
    assert payload["artifact_candidate"] == manifest["bundle_artifact_candidate"]
    assert payload["selection_incumbent"] == manifest["bundle_selection_incumbent"]
    assert payload["n_features"] == len(manifest["shipped_feature_columns"])
    assert payload["in_unit_interval"] is True
    assert len(payload["predictions_sha"]) == 64
