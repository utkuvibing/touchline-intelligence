"""Inc 8 dry run: run the real ``touchline.modeling.train`` CLI end-to-end on a seeded database.

This is the plumbing smoke test that runs before the full-cohort evidence: it seeds a synthetic
development cohort in an isolated schema where **every validation fold contains both classes**
(so the single-class loud-failure can never hide), writes a config with the synthetic anchors and
byte-pin hashes, and invokes ``main()`` with the test seam overrides (``--assignments-csv``,
``--cohort-sql``). It asserts the experiment record is written canonically and that a tampered
(pinned-hash-mismatching) config fails loudly before anything is written.

The committed-artifact defaults of ``main()`` stay the production lock; only this test passes the
overrides. The real 2,872-row run is Inc 9 and uses no overrides.
"""

from __future__ import annotations

import hashlib
import json
import os
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

from touchline.modeling.dataset import ArtifactHashMismatchError
from touchline.modeling.train import main as train_main

DB_URL = os.environ.get("TOUCHLINE_DB_URL")
TEST_SCHEMA = "wp24_train_dry_run"
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


def _write_config(tmp_path: Path, assignments_sha256: str, *, tamper_hash: bool = False) -> Path:
    config = {
        "experiment_id": "exp-dry-run-test",
        "out_dir": str(tmp_path / "exp"),
        "artifacts_dir": str(tmp_path / "artifacts"),
        "code_commit": "test-dry-run",
        "data_source_commit": "b0bc9f22dd77c206ddedc1d742893b3bbe64baec",
        "db_url_env": "TOUCHLINE_DB_URL",
        "assignments_sha256": ("0" * 64) if tamper_hash else assignments_sha256,
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


def test_dry_run_writes_a_canonical_experiment_record(
    conn: psycopg.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_cohort(conn)
    assignments_csv = tmp_path / "assignments.csv"
    assignments_csv.write_text(SYN_ASSIGNMENTS, encoding="utf-8", newline="\n")
    assignments_sha = hashlib.sha256(assignments_csv.read_bytes()).hexdigest()
    config_path = _write_config(tmp_path, assignments_sha)

    monkeypatch.setenv("TOUCHLINE_TRAIN_SCHEMA", TEST_SCHEMA)
    assert DB_URL is not None
    monkeypatch.setenv("TOUCHLINE_DB_URL", DB_URL)

    exit_code = train_main(
        [
            "--config",
            str(config_path),
            "--assignments-csv",
            str(assignments_csv),
            "--code-commit",
            "test-dry-run",
        ]
    )
    assert exit_code == 0

    exp_dir = tmp_path / "exp"
    for name in ("metrics.json", "config.json", "notes.md", "artifact-manifest.json"):
        assert (exp_dir / name).exists()
    assert (tmp_path / "artifacts" / "model.pkl").exists()

    raw = (exp_dir / "metrics.json").read_bytes()
    assert raw.endswith(b"\n") and not raw.endswith(b"\r\n")
    metrics = json.loads(raw)
    assert metrics["n_rows"] == EXPECTED_SHOTS
    assert metrics["n_matches"] == EXPECTED_MATCHES
    assert isinstance(metrics["d5"]["include"], bool)
    assert metrics["d5_include"] is metrics["d5"]["include"]
    assert metrics["protocol_incumbent"] in {
        "constant",
        "geometry_logistic",
        "full_logistic",
        "full_minus_presence",
    }
    assert metrics["shipped_candidate"] in {"full_logistic", "full_minus_presence"}
    assert isinstance(metrics["shipped_feature_columns"], list)
    shipped = metrics["shipped_candidate"]
    assert metrics["shipped_best_c"] == metrics["candidates"][shipped]["best_c"]
    # The shipped feature set must be machine-consistent with the decision.
    if metrics["d5_include"]:
        assert metrics["shipped_feature_set"] == "geometry+categoricals+presence-indicators"
        assert any("_presence" in c for c in metrics["shipped_feature_columns"])
    else:
        assert metrics["shipped_feature_set"] == "geometry+categoricals"
        assert not any("_presence" in c for c in metrics["shipped_feature_columns"])
    assert set(metrics["presence_report"]) == {"first_time", "under_pressure"}

    # One authoritative results row describing the shipped candidate (correction 3).
    results = (tmp_path / "results.csv").read_text(encoding="utf-8")
    rows = [line for line in results.splitlines()[1:] if line.strip()]
    matching = [r for r in rows if r.split(",")[0] == "exp-dry-run-test"]
    assert len(matching) == 1
    meta = {
        k: v
        for k, v in zip(results.splitlines()[0].split(","), matching[0].split(","), strict=True)
    }
    assert meta["shipped_candidate"] == metrics["shipped_candidate"]
    assert meta["d5_include"] == str(metrics["d5_include"])
    assert meta["protocol_incumbent"] == metrics["protocol_incumbent"]
    assert meta["code_commit"] == "test-dry-run"

    # Bundled artifact must be self-contained and describe the shipped candidate.
    manifest = json.loads((exp_dir / "artifact-manifest.json").read_text(encoding="utf-8"))
    assert manifest["shipped_candidate"] == metrics["shipped_candidate"]
    assert manifest["shipped_feature_columns"] == metrics["shipped_feature_columns"]
    recorded_hash = manifest["model_pickle_sha256"]
    import hashlib as _hashlib

    actual = _hashlib.sha256((tmp_path / "artifacts" / "model.pkl").read_bytes()).hexdigest()
    assert recorded_hash == actual


def test_dry_run_fails_loudly_on_pinned_hash_mismatch(
    conn: psycopg.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_cohort(conn)
    assignments_csv = tmp_path / "assignments.csv"
    assignments_csv.write_text(SYN_ASSIGNMENTS, encoding="utf-8", newline="\n")
    assignments_sha = hashlib.sha256(assignments_csv.read_bytes()).hexdigest()
    config_path = _write_config(tmp_path, assignments_sha, tamper_hash=True)

    monkeypatch.setenv("TOUCHLINE_TRAIN_SCHEMA", TEST_SCHEMA)
    assert DB_URL is not None
    monkeypatch.setenv("TOUCHLINE_DB_URL", DB_URL)

    with pytest.raises(ArtifactHashMismatchError):
        train_main(
            [
                "--config",
                str(config_path),
                "--assignments-csv",
                str(assignments_csv),
                "--code-commit",
                "test-dry-run",
            ]
        )
    assert not (tmp_path / "exp" / "metrics.json").exists()
