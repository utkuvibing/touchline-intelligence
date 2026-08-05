"""Integration contracts for the WP2.4 development-cohort loader's structural lock.

Seeds synthetic matches in *all four* locked scopes (development, calibration, holdout and an
outside scope is not needed — the four core scopes are enough) with known outcomes, then asserts:

- the loader returns development rows only (holdout and calibration rows stay in the database but
  never reach the loader's result set — the lock is a filter, not a delete);
- per-match fold assignment comes from the parsed assignment CSV;
- the full verification chain (canonical CSV hash check + cohort-SQL hash check + parse + load)
  runs end-to-end on synthetic data with a named error on any deviation;
- the locked development anchors pass when the caller supplies the synthetic expected sizes.

The real 2,872-row / 115-match / fold-{570,552,602,576,572} anchors are asserted by the
full-cohort module (``test_wp2_4_training_full_cohort.py``) against the local ingested database;
this module proves the *structural* lock on a deterministic small population.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from support.db_safety import connect_local

from touchline.ingest.migrate import apply_migrations
from touchline.modeling.dataset import (
    CohortSizeError,
    load_development_cohort,
    parse_match_assignments,
    verify_assignments_csv,
    verify_cohort_sql,
    verify_development_anchor,
)

DB_URL = os.environ.get("TOUCHLINE_DB_URL")
TEST_SCHEMA = "wp24_dataset_test"
ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "data" / "model" / "wp2_3_split_manifest.json"
CSV_PATH = ROOT / "data" / "model" / "wp2_3_match_assignments.csv"
COHORT_SQL_PATH = ROOT / "backend" / "sql" / "wp2_1" / "01_model_shot_cohort.sql"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(DB_URL is None, reason="TOUCHLINE_DB_URL is not set"),
]

#: Synthetic match set covering all four locked scopes.
#: development: 101..104 (folds 0..3 by sorted match id), calibration: 201, holdout: 301.
SYN_ASSIGNMENTS = "\n".join(
    [
        "match_id,competition_id,season_id,match_date,split,fold",
        "101,43,3,2018-06-14,development,0",
        "102,43,3,2018-06-15,development,1",
        "103,55,43,2020-06-11,development,2",
        "104,55,43,2020-06-12,development,3",
        "201,43,106,2022-11-20,calibration,",
        "301,55,282,2024-06-14,holdout,",
        "",
    ]
)

SYN_EXPECTED_SHOTS = 5
SYN_EXPECTED_MATCHES = 4
# Match 101 (fold 0) carries two shots; 102, 103, 104 (folds 1, 2, 3) one each; fold 4 empty.
SYN_EXPECTED_FOLDS = {0: 2, 1: 1, 2: 1, 3: 1, 4: 0}


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
        for match_id, comp, season, date in (
            (101, 43, 3, "2018-06-14"),
            (102, 43, 3, "2018-06-15"),
            (103, 55, 43, "2020-06-11"),
            (104, 55, 43, "2020-06-12"),
            (201, 43, 106, "2022-11-20"),
            (301, 55, 282, "2024-06-14"),
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

        # One or two eligible shots per development match; one each in calibration and holdout.
        # Rows: (event_number, match_id, index, goal)
        shots = [
            (1, 101, 1, True),
            (2, 101, 2, False),
            (3, 102, 1, True),
            (4, 103, 1, False),
            (5, 104, 1, True),
            (6, 201, 1, False),  # calibration
            (7, 301, 1, True),  # holdout
        ]
        for number, match_id, index, goal in shots:
            cur.execute(
                """
                INSERT INTO events (
                    event_id, match_id, event_index, period, team_id, player_id,
                    event_type_name, location_x, location_y, play_pattern_id, play_pattern_name
                ) VALUES (%s::uuid, %s, %s, 1, 1, 10, 'Shot', %s, %s, 1, 'Regular Play')
                """,
                (f"00000000-0000-0000-0000-{number:012d}", match_id, index, 100.0, 40.0),
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


def _synthetic_csv_bytes() -> bytes:
    return SYN_ASSIGNMENTS.encode("utf-8")


def test_loader_returns_development_rows_only_with_the_structural_lock(
    conn: psycopg.Connection,
) -> None:
    _seed(conn)

    csv_bytes = _synthetic_csv_bytes()
    verify_assignments_csv(csv_bytes, hashlib.sha256(csv_bytes).hexdigest())
    assignments = parse_match_assignments(SYN_ASSIGNMENTS)
    cohort_sql = verify_cohort_sql(
        COHORT_SQL_PATH.read_bytes(),
        _manifest_field("cohort_sql_sha256"),
    )

    rows = load_development_cohort(conn, cohort_sql, assignments)

    assert {row.match_id for row in rows} <= {101, 102, 103, 104}
    assert {row.match_id for row in rows} == {101, 102, 103, 104}
    assert len(rows) == SYN_EXPECTED_SHOTS
    fold_of = {row.match_id: row.fold for row in rows}
    assert fold_of == {101: 0, 102: 1, 103: 2, 104: 3}
    goals = {row.shot_id for row in rows if row.y == 1}
    assert len(goals) == 3  # events 1, 3, 5
    # Field mapping guard: a rotation (body<->technique<->play-pattern) must never pass silently.
    assert all(row.body_part_name == "Right Foot" for row in rows)
    assert all(row.technique_name == "Normal" for row in rows)
    assert all(row.play_pattern_name == "Regular Play" for row in rows)
    assert all(row.competition_id in (43, 55) for row in rows)
    verify_development_anchor(
        rows,
        expected_shots=SYN_EXPECTED_SHOTS,
        expected_matches=SYN_EXPECTED_MATCHES,
        expected_fold_sizes=SYN_EXPECTED_FOLDS,
    )


def test_calibration_and_holdout_rows_stay_in_the_database_but_are_not_returned(
    conn: psycopg.Connection,
) -> None:
    _seed(conn)

    assignments = parse_match_assignments(SYN_ASSIGNMENTS)
    cohort_sql = verify_cohort_sql(
        COHORT_SQL_PATH.read_bytes(),
        _manifest_field("cohort_sql_sha256"),
    )
    rows = load_development_cohort(conn, cohort_sql, assignments)

    # The lock is a filter, not a delete: the calibration and holdout shots are present in the DB.
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM events WHERE event_type_name = 'Shot'")
        row = cur.fetchone()
        assert row is not None
        total = row[0]
    assert total == 7
    assert {row.match_id for row in rows} == {101, 102, 103, 104}
    assert all(row.match_id not in frozenset({201, 301}) for row in rows)


def test_loader_fails_loudly_on_a_wrong_development_anchor(conn: psycopg.Connection) -> None:
    _seed(conn)
    assignments = parse_match_assignments(SYN_ASSIGNMENTS)
    cohort_sql = verify_cohort_sql(
        COHORT_SQL_PATH.read_bytes(),
        _manifest_field("cohort_sql_sha256"),
    )
    rows = load_development_cohort(conn, cohort_sql, assignments)
    with pytest.raises(CohortSizeError):
        # Locked full-cohort constants do not match the smaller synthetic population.
        verify_development_anchor(rows)


def _manifest_field(key: str) -> str:
    import json

    value = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))[key]
    assert isinstance(value, str)
    return value
