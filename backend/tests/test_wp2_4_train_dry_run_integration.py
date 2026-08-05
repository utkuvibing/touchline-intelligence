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

from touchline.ingest.migrate import apply_migrations
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


#: 10 development matches, 2 per fold (fold = index % 5), each with one goal and one saved shot,
#: so every fold's validation set has both classes. Matches 200..204 are WC 2018, 205..209 are
#: Euro 2020. Matches 230 (calibration) and 240 (holdout) are seeded but absent from the synthetic
#: assignment CSV, proving the loader never touches them.
def _build_assignments() -> str:
    lines = ["match_id,competition_id,season_id,match_date,split,fold"]
    for i in range(10):
        if i < 5:
            line = f"{200 + i},43,3,2018-06-{14 + i:02d},development,{i % 5}"
        else:
            line = f"{200 + i},55,43,2020-06-{11 + i - 5:02d},development,{i % 5}"
        lines.append(line)
    return "\n".join(lines) + "\n"


SYN_ASSIGNMENTS = _build_assignments()
EXPECTED_SHOTS = 20
EXPECTED_MATCHES = 10
EXPECTED_FOLDS = {0: 4, 1: 4, 2: 4, 3: 4, 4: 4}


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


def _seed(conn: psycopg.Connection) -> None:
    apply_migrations(conn)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO competitions VALUES "
            "(43, 'World Cup', 'International'), (55, 'European Championship', 'International')"
        )
        cur.execute(
            "INSERT INTO seasons VALUES (3, '2018'), (43, '2020'), (106, '2022'), (282, '2024')"
        )
        cur.execute(
            "INSERT INTO competition_seasons VALUES (43, 3), (55, 43), (43, 106), (55, 282)"
        )
        cur.execute("INSERT INTO teams VALUES (1, 'Home'), (2, 'Away')")
        cur.execute("INSERT INTO players VALUES (10, 'Shooter')")

        for i in range(10):
            match_id = 200 + i
            comp, season, date = (
                (43, 3, f"2018-06-{14 + i:02d}") if i < 5 else (55, 43, f"2020-06-{11 + i - 5:02d}")
            )
            cur.execute(
                "INSERT INTO matches (match_id, competition_id, season_id, match_date, "
                "home_team_id, away_team_id, home_score, away_score) "
                "VALUES (%s, %s, %s, %s::date, 1, 2, 0, 0)",
                (match_id, comp, season, date),
            )
            cur.execute(
                "INSERT INTO match_teams VALUES (%s, 1, 'home'), (%s, 2, 'away')",
                (match_id, match_id),
            )
        for match_id, comp, season, date in (
            (230, 43, 106, "2022-11-20"),
            (240, 55, 282, "2024-06-14"),
        ):
            cur.execute(
                "INSERT INTO matches (match_id, competition_id, season_id, match_date, "
                "home_team_id, away_team_id, home_score, away_score) "
                "VALUES (%s, %s, %s, %s::date, 1, 2, 0, 0)",
                (match_id, comp, season, date),
            )
            cur.execute(
                "INSERT INTO match_teams VALUES (%s, 1, 'home'), (%s, 2, 'away')",
                (match_id, match_id),
            )

        for i in range(10):
            match_id = 200 + i
            for shot_index, goal in ((0, True), (1, False)):
                number = 2 * i + shot_index + 1
                location_x = 88.0 + (number % 13)
                location_y = 30.0 + (number % 9)
                cur.execute(
                    """
                    INSERT INTO events (
                        event_id, match_id, event_index, period, team_id, player_id,
                        event_type_name, location_x, location_y, play_pattern_id,
                        play_pattern_name, under_pressure
                    ) VALUES (%s::uuid, %s, %s, 1, 1, 10, 'Shot', %s, %s, 1, 'Regular Play', %s)
                    """,
                    (
                        f"00000000-0000-0000-0000-{number:012d}",
                        match_id,
                        shot_index + 1,
                        location_x,
                        location_y,
                        True if i == 0 else None,
                    ),
                )
                cur.execute(
                    """
                    INSERT INTO shots (
                        event_id, outcome_id, outcome_name, body_part_id, body_part_name,
                        technique_id, technique_name, shot_type_id, shot_type_name, first_time
                    ) VALUES (%s::uuid, %s, %s, 40, 'Right Foot', 93, 'Normal', 87, 'Open Play', %s)
                    """,
                    (
                        f"00000000-0000-0000-0000-{number:012d}",
                        97 if goal else 96,
                        "Goal" if goal else "Saved",
                        True if i in (1, 2) and not shot_index else None,
                    ),
                )
        # Calibration and holdout shots exist in the database but are not in the assignment CSV.
        for number, match_id, goal in ((81, 230, False), (82, 240, True)):
            cur.execute(
                """
                INSERT INTO events (
                    event_id, match_id, event_index, period, team_id, player_id,
                    event_type_name, location_x, location_y, play_pattern_id, play_pattern_name
                ) VALUES (%s::uuid, %s, 1, 1, 1, 10, 'Shot', %s, %s, 1, 'Regular Play')
                """,
                (f"00000000-0000-0000-0000-{number:012d}", match_id, 100.0, 40.0),
            )
            cur.execute(
                """
                INSERT INTO shots (
                    event_id, outcome_id, outcome_name, body_part_id, body_part_name,
                    technique_id, technique_name, shot_type_id, shot_type_name
                ) VALUES (%s::uuid, %s, %s, 40, 'Right Foot', 93, 'Normal', 87, 'Open Play')
                """,
                (
                    f"00000000-0000-0000-0000-{number:012d}",
                    97 if goal else 96,
                    "Goal" if goal else "Saved",
                ),
            )
    conn.commit()


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
    _seed(conn)
    assignments_csv = tmp_path / "assignments.csv"
    assignments_csv.write_text(SYN_ASSIGNMENTS, encoding="utf-8", newline="\n")
    assignments_sha = hashlib.sha256(assignments_csv.read_bytes()).hexdigest()
    config_path = _write_config(tmp_path, assignments_sha)

    monkeypatch.setenv("TOUCHLINE_TRAIN_SCHEMA", TEST_SCHEMA)
    assert DB_URL is not None
    monkeypatch.setenv("TOUCHLINE_DB_URL", DB_URL)

    exit_code = train_main(
        ["--config", str(config_path), "--assignments-csv", str(assignments_csv)]
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
    _seed(conn)
    assignments_csv = tmp_path / "assignments.csv"
    assignments_csv.write_text(SYN_ASSIGNMENTS, encoding="utf-8", newline="\n")
    assignments_sha = hashlib.sha256(assignments_csv.read_bytes()).hexdigest()
    config_path = _write_config(tmp_path, assignments_sha, tamper_hash=True)

    monkeypatch.setenv("TOUCHLINE_TRAIN_SCHEMA", TEST_SCHEMA)
    assert DB_URL is not None
    monkeypatch.setenv("TOUCHLINE_DB_URL", DB_URL)

    with pytest.raises(ArtifactHashMismatchError):
        train_main(["--config", str(config_path), "--assignments-csv", str(assignments_csv)])
    assert not (tmp_path / "exp" / "metrics.json").exists()
