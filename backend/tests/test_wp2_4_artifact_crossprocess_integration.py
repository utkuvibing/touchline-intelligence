"""P0 cross-process artifact contract: CLI-generated model.pkl loads in a fresh process.

The documented execution path is ``python -m touchline.modeling.train``. This test generates the
artifact through that exact CLI path (a separate ``sys.executable`` process, never ``train.main()``
in-process), then starts **another** fresh Python process that imports the stable artifact module,
``load_bundle``-loads ``model.pkl``, builds raw ``ShotRow`` objects and scores them. It asserts:

- the loaded object is ``touchline.modeling.artifact.ArtifactBundle`` (not ``__main__``-bound);
- candidate and feature count match the recorded manifest;
- probabilities are finite and in [0, 1];
- no preprocessing is re-fitted (inference uses persisted scaler/vocabulary only).

The isolated integration database/schema pattern is preserved (READ ONLY load, isolated schema,
teardown drops the schema) and the git-ignored ``model.pkl`` is written only under a temp
``artifacts_dir``.
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
from support.wp24_synthetic import (
    EXPECTED_FOLDS,
    EXPECTED_MATCHES,
    EXPECTED_SHOTS,
    SYN_ASSIGNMENTS,
    seed_cohort,
)

DB_URL = os.environ.get("TOUCHLINE_DB_URL")
TEST_SCHEMA = "wp24_artifact_crossprocess"
ROOT = Path(__file__).resolve().parents[2]
COHORT_SQL_PATH = ROOT / "backend" / "sql" / "wp2_1" / "01_model_shot_cohort.sql"
MANIFEST_PATH = ROOT / "data" / "model" / "wp2_3_split_manifest.json"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(DB_URL is None, reason="TOUCHLINE_DB_URL is not set"),
]


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    assert DB_URL is not None
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


def _manifest_hash(key: str) -> str:
    value = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))[key]
    assert isinstance(value, str)
    return value


def _write_config(tmp_path: Path, assignments_sha: str) -> Path:
    config = {
        "experiment_id": "exp-crossprocess",
        "out_dir": str(tmp_path / "exp"),
        "artifacts_dir": str(tmp_path / "artifacts"),
        "data_source_commit": "b0bc9f22dd77c206ddedc1d742893b3bbe64baec",
        "db_url_env": "TOUCHLINE_DB_URL",
        "require_clean_provenance": False,
        "assignments_sha256": assignments_sha,
        "cohort_sql_sha256": _manifest_hash("cohort_sql_sha256"),
        "c_grid": [0.01, 0.1, 1.0, 10.0],
        "random_seed": 0,
        "n_folds": 5,
        "expected_shots": EXPECTED_SHOTS,
        "expected_matches": EXPECTED_MATCHES,
        "expected_fold_sizes": {str(k): v for k, v in EXPECTED_FOLDS.items()},
        "bin_count": 5,
        "results_csv": str(tmp_path / "results.csv"),
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return path


def test_cli_generated_pickle_loads_and_scores_in_a_fresh_process(
    conn: psycopg.Connection, tmp_path: Path
) -> None:
    seed_cohort(conn)

    assignments_csv = tmp_path / "assignments.csv"
    assignments_csv.write_text(SYN_ASSIGNMENTS, encoding="utf-8", newline="\n")
    assignments_sha = hashlib.sha256(assignments_csv.read_bytes()).hexdigest()
    config_path = _write_config(tmp_path, assignments_sha)

    assert DB_URL is not None
    env = {
        **os.environ,
        "TOUCHLINE_DB_URL": DB_URL,
        "TOUCHLINE_TRAIN_SCHEMA": TEST_SCHEMA,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "touchline.modeling.train",
            "--config",
            str(config_path),
            "--assignments-csv",
            str(assignments_csv),
            "--code-commit",
            "crossproc",
        ],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert run.returncode == 0, f"CLI failed:\n{run.stdout}\n{run.stderr}"

    pkl = tmp_path / "artifacts" / "model.pkl"
    assert pkl.exists()
    manifest = json.loads((tmp_path / "exp" / "artifact-manifest.json").read_text(encoding="utf-8"))
    expected_candidate = manifest["shipped_candidate"]
    expected_n_features = len(manifest["shipped_feature_columns"])

    child = """
import json, sys
from touchline.modeling.artifact import ArtifactBundle, load_bundle, infer
from touchline.modeling.preprocessing import ShotRow

bundle = load_bundle(sys.argv[1])
rows = [
    ShotRow("x1", 201, 1, 43, 3, 0, 15.0, 0.4, "Right Foot", "Normal",
            "Regular Play", None, None),
    ShotRow("x2", 202, 2, 43, 3, 1, 8.0, 0.6, "Head", "Volley",
            "From Corner", None, None),
]
p = infer(bundle, rows)
print(json.dumps({
    "module": type(bundle).__module__,
    "qualname": type(bundle).__qualname__,
    "candidate": bundle.shipped_candidate,
    "n_features": len(bundle.selected_columns),
    "probs": [float(x) for x in p],
}))
"""
    child_run = subprocess.run(
        [sys.executable, "-c", child, str(pkl)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert child_run.returncode == 0, (
        f"fresh process failed:\n{child_run.stdout}\n{child_run.stderr}"
    )
    payload = json.loads(child_run.stdout.strip().splitlines()[-1])

    assert payload["module"] == "touchline.modeling.artifact"
    assert payload["qualname"] == "ArtifactBundle"
    assert payload["candidate"] == expected_candidate
    assert payload["n_features"] == expected_n_features
    assert len(payload["probs"]) == 2
    for value in payload["probs"]:
        assert value == value, "NaN probability"  # finite
        assert 0.0 <= value <= 1.0
    assert isinstance(manifest["model_pickle_sha256"], str)
    assert hashlib.sha256(pkl.read_bytes()).hexdigest() == manifest["model_pickle_sha256"]
