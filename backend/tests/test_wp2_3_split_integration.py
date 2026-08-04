"""Fixture-based contracts for the WP2.3 split SQL and assignment. Runs in CI.

The module builds an isolated schema, seeds fictional matches and shots spanning all four locked
scope pairs, then proves the split contract end-to-end: both queries are read-only, the match
population and shot membership agree with the duplicated WP2.1 predicate set, every eligible shot
joins exactly one match assignment and exactly one top-level split, folds are deterministic and
disjoint, chronology holds between the top-level splits, NULL match dates raise explicitly, and
the assignment is insensitive to input row order.

The WP2.1 cohort query is executed here only to compare `shot_id` sets (its first column). No
outcome value from any query enters WP2.3's split logic, artifacts, protocol decisions, or
assertions — see `backend/sql/wp2_3/README.md` for the precise target-access boundary. Both WP2.3
queries duplicate WP2.1's eligibility predicate set, which includes the inherited
`outcome_name IS NOT NULL` check; they never inspect outcome categories or project the target.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from support.db_safety import connect_local

from touchline.ingest.migrate import apply_migrations
from touchline.modeling.splits import (
    MatchRecord,
    SplitAssignmentError,
    assign_tournament_split,
)

DB_URL = os.environ.get("TOUCHLINE_DB_URL")
TEST_SCHEMA = "wp23_split_test"
SQL_DIR = Path(__file__).parents[1] / "sql" / "wp2_3"
WP21_SQL_DIR = Path(__file__).parents[1] / "sql" / "wp2_1"

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


def _seed_split_fixture(conn: psycopg.Connection, include_null_date_match: bool = False) -> None:
    apply_migrations(conn)
    with conn.cursor() as cur:
        # The production constraint rejects half-missing coordinate pairs. Drop it only in this
        # adversarial fixture so the excluded-row predicates are independently observable.
        cur.execute("ALTER TABLE events DROP CONSTRAINT events_location_pair_complete")
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
        # match_id: 100-103 dev WC2018, 200-202 dev Euro2020, 300-302 calibration WC2022,
        # 400-401 holdout Euro2024. 101/102 share a date to exercise the match_id tie-break;
        # 101 has no shots at all to prove zero-shot matches are still assigned.
        matches: list[tuple[int, int, int, str | None]] = [
            (100, 43, 3, "2018-06-01"),
            (101, 43, 3, "2018-06-14"),
            (102, 43, 3, "2018-06-14"),
            (103, 43, 3, "2018-06-20"),
            (200, 55, 43, "2021-06-11"),
            (201, 55, 43, "2021-06-20"),
            (202, 55, 43, "2021-06-30"),
            (300, 43, 106, "2022-11-20"),
            (301, 43, 106, "2022-12-03"),
            (302, 43, 106, "2022-12-18"),
            (400, 55, 282, "2024-06-14"),
            (401, 55, 282, "2024-07-14"),
        ]
        if include_null_date_match:
            matches.append((500, 43, 3, None))
        for match_id, competition_id, season_id, match_date in matches:
            cur.execute(
                """
                INSERT INTO matches (
                    match_id, competition_id, season_id, match_date,
                    home_team_id, away_team_id, home_score, away_score
                ) VALUES (%s, %s, %s, %s, 1, 2, 0, 0)
                """,
                (match_id, competition_id, season_id, match_date),
            )
            cur.execute(
                "INSERT INTO match_teams VALUES (%s, 1, 'home'), (%s, 2, 'away')",
                (match_id, match_id),
            )

        # (event_number, match_id, event_index, period, x, y, event_type)
        events = [
            (1, 100, 1, 1, 100.0, 40.0, "Shot"),
            (2, 100, 2, 1, 95.0, 35.0, "Shot"),
            (3, 100, 3, 1, 108.0, 40.0, "Shot"),
            (4, 102, 1, 1, 90.0, 30.0, "Shot"),
            (5, 103, 1, 5, 95.0, 38.0, "Shot"),
            (6, 200, 1, 1, 100.0, 40.0, "Shot"),
            (7, 200, 2, 1, 99.0, 39.0, "Shot"),
            (8, 300, 1, 1, 108.0, 40.0, "Shot"),
            (9, 302, 1, 1, None, None, "Shot"),
            (10, 400, 1, 1, 101.0, 41.0, "Shot"),
            (11, 400, 2, 1, 100.0, 40.0, "Shot"),
            (12, 401, 1, 1, 97.0, 32.0, "Shot"),
        ]
        for number, match_id, index, period, x, y, event_type in events:
            cur.execute(
                """
                INSERT INTO events (
                    event_id, match_id, event_index, period, team_id, player_id,
                    event_type_name, location_x, location_y, play_pattern_id, play_pattern_name
                ) VALUES (%s::uuid, %s, %s, %s, 1, 10, %s, %s, %s, 1, 'Regular Play')
                """,
                (
                    f"00000000-0000-0000-0000-{number:012d}",
                    match_id,
                    index,
                    period,
                    event_type,
                    x,
                    y,
                ),
            )

        # (event_number, outcome_id, outcome_name, body_part_id, body_part_name,
        #  technique_id, technique_name, shot_type_id, shot_type_name)
        # Excluded rows: 3 (Penalty type), 5 (period 5), 7 (NULL outcome),
        # 9 (NULL location pair), 11 (NULL body part).
        shot_rows = {
            1: (97, "Goal", 40, "Right Foot", 93, "Normal", 87, "Open Play"),
            2: (96, "Saved", 40, "Right Foot", 93, "Normal", 87, "Open Play"),
            3: (97, "Goal", 40, "Right Foot", 93, "Normal", 88, "Penalty"),
            4: (97, "Goal", 38, "Left Foot", 93, "Normal", 87, "Open Play"),
            5: (97, "Goal", 40, "Right Foot", 93, "Normal", 87, "Open Play"),
            6: (96, "Saved", 46, "Head", 93, "Normal", 87, "Open Play"),
            7: (None, None, 40, "Right Foot", 93, "Normal", 87, "Open Play"),
            8: (97, "Goal", 40, "Right Foot", 93, "Normal", 87, "Open Play"),
            9: (96, "Saved", 40, "Right Foot", 93, "Normal", 87, "Open Play"),
            10: (97, "Goal", 40, "Right Foot", 93, "Normal", 87, "Open Play"),
            11: (96, "Saved", None, None, 93, "Normal", 87, "Open Play"),
            12: (96, "Saved", 40, "Right Foot", 93, "Normal", 87, "Open Play"),
        }
        for number, values in shot_rows.items():
            cur.execute(
                """
                INSERT INTO shots (
                    event_id, outcome_id, outcome_name, body_part_id, body_part_name,
                    technique_id, technique_name, shot_type_id, shot_type_name
                ) VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (f"00000000-0000-0000-0000-{number:012d}", *values),
            )
    conn.commit()


def _run_query(conn: psycopg.Connection, number: int) -> tuple[list[str], list[tuple[object, ...]]]:
    path = sorted(SQL_DIR.glob("[0-9][0-9]_*.sql"))[number - 1]
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(path.read_text(encoding="utf-8"))
        assert cur.description is not None
        columns = [column.name for column in cur.description]
        return columns, list(cur.fetchall())


def _run_wp21_cohort(conn: psycopg.Connection) -> list[tuple[object, ...]]:
    """Run WP2.1's cohort query and return its rows; only the `shot_id` column is consumed."""
    path = WP21_SQL_DIR / "01_model_shot_cohort.sql"
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(path.read_text(encoding="utf-8"))
        return list(cur.fetchall())


def _int(value: object) -> int:
    """Every numeric column in both queries is an integer; anything else is a query change."""
    assert isinstance(value, int), value
    return value


def _records_from_rows(rows: list[tuple[object, ...]]) -> list[MatchRecord]:
    return [
        MatchRecord(
            match_id=_int(row[0]),
            competition_id=_int(row[1]),
            season_id=_int(row[2]),
            match_date=row[3] if isinstance(row[3], dt.date) else None,
        )
        for row in rows
    ]


def _date_value(value: object) -> dt.date:
    """Every match date column in query 01 is a date; anything else is a query change."""
    assert isinstance(value, dt.date), value
    return value


def _eligible_shots_by_match(rows: list[tuple[object, ...]]) -> dict[int, int]:
    return {_int(row[0]): _int(row[4]) for row in rows}


#: (match_id, split, fold); fold is None outside development.
EXPECTED_ASSIGNMENT = {
    100: ("development", 0),
    101: ("development", 1),
    102: ("development", 2),
    103: ("development", 3),
    200: ("development", 4),
    201: ("development", 0),
    202: ("development", 1),
    300: ("calibration", None),
    301: ("calibration", None),
    302: ("calibration", None),
    400: ("holdout", None),
    401: ("holdout", None),
}

#: (match_id, eligible_shots) as counted by the duplicated WP2.1 predicate set.
EXPECTED_ELIGIBLE_SHOTS = {
    100: 2,
    101: 0,
    102: 1,
    103: 0,
    200: 1,
    201: 0,
    202: 0,
    300: 1,
    301: 0,
    302: 0,
    400: 1,
    401: 1,
}

#: shot numbers that satisfy the cohort predicates (eligible).
EXPECTED_ELIGIBLE_SHOT_IDS = {
    uuid.UUID(f"00000000-0000-0000-0000-{number:012d}") for number in (1, 2, 4, 6, 8, 10, 12)
}


def test_queries_run_read_only_with_the_declared_grains(conn: psycopg.Connection) -> None:
    _seed_split_fixture(conn)

    columns_01, rows_01 = _run_query(conn, 1)
    assert columns_01 == ["match_id", "competition_id", "season_id", "match_date", "eligible_shots"]
    assert len(rows_01) == 12

    columns_02, rows_02 = _run_query(conn, 2)
    assert columns_02 == ["shot_id", "match_id"]
    assert len(rows_02) == 7


def test_match_population_counts_eligible_shots_per_match(conn: psycopg.Connection) -> None:
    _seed_split_fixture(conn)

    _, rows_01 = _run_query(conn, 1)
    assert _eligible_shots_by_match(rows_01) == EXPECTED_ELIGIBLE_SHOTS
    assert sum(EXPECTED_ELIGIBLE_SHOTS.values()) == 7


def test_shot_membership_is_set_equal_to_the_wp21_cohort(conn: psycopg.Connection) -> None:
    """The shot-level partition query admits exactly the WP2.1 cohort ids and no others."""
    _seed_split_fixture(conn)

    _, rows_02 = _run_query(conn, 2)
    wp21_rows = _run_wp21_cohort(conn)

    wp23_ids = {row[0] for row in rows_02}
    wp21_ids = {row[0] for row in wp21_rows}
    assert wp23_ids == EXPECTED_ELIGIBLE_SHOT_IDS
    assert wp21_ids == EXPECTED_ELIGIBLE_SHOT_IDS
    assert wp23_ids == wp21_ids


def test_assignment_partition_folds_and_chronology(conn: psycopg.Connection) -> None:
    _seed_split_fixture(conn)

    _, rows_01 = _run_query(conn, 1)
    plan = assign_tournament_split(_records_from_rows(rows_01))

    assert set(plan.match_split) == set(EXPECTED_ASSIGNMENT)
    for match_id, (split, fold) in EXPECTED_ASSIGNMENT.items():
        assert plan.split_of(match_id) == split
        if fold is None:
            with pytest.raises(SplitAssignmentError):
                plan.fold_of(match_id)
        else:
            assert plan.fold_of(match_id) == fold

    dev_dates = {
        _date_value(row[3]) for row in rows_01 if plan.split_of(_int(row[0])) == "development"
    }
    calib_dates = {
        _date_value(row[3]) for row in rows_01 if plan.split_of(_int(row[0])) == "calibration"
    }
    holdout_dates = {
        _date_value(row[3]) for row in rows_01 if plan.split_of(_int(row[0])) == "holdout"
    }
    assert max(dev_dates) < min(calib_dates)
    assert max(calib_dates) < min(holdout_dates)


def test_every_eligible_shot_belongs_to_exactly_one_split(conn: psycopg.Connection) -> None:
    _seed_split_fixture(conn)

    _, rows_01 = _run_query(conn, 1)
    _, rows_02 = _run_query(conn, 2)
    plan = assign_tournament_split(_records_from_rows(rows_01))

    shot_ids = [row[0] for row in rows_02]
    assert len(shot_ids) == len(set(shot_ids))
    shot_splits = [plan.split_of(_int(row[1])) for row in rows_02]
    assert shot_splits.count("development") == 4
    assert shot_splits.count("calibration") == 1
    assert shot_splits.count("holdout") == 2
    for row in rows_02:
        assert _int(row[1]) in plan.match_split


def test_per_match_count_agreement_between_both_queries(conn: psycopg.Connection) -> None:
    """Query 01's eligible_shots equals query 02 grouped by match, for every match."""
    _seed_split_fixture(conn)

    _, rows_01 = _run_query(conn, 1)
    _, rows_02 = _run_query(conn, 2)

    grouped: dict[int, int] = {}
    for row in rows_02:
        match_id = _int(row[1])
        grouped[match_id] = grouped.get(match_id, 0) + 1

    for row in rows_01:
        match_id = _int(row[0])
        assert grouped.get(match_id, 0) == _int(row[4]), match_id


def test_null_match_date_fails_explicitly(conn: psycopg.Connection) -> None:
    _seed_split_fixture(conn, include_null_date_match=True)

    _, rows_01 = _run_query(conn, 1)
    with pytest.raises(SplitAssignmentError, match=r"match 500 has no match_date"):
        assign_tournament_split(_records_from_rows(rows_01))


def test_assignment_is_deterministic_under_row_order_changes(conn: psycopg.Connection) -> None:
    _seed_split_fixture(conn)

    _, rows_01 = _run_query(conn, 1)
    records = _records_from_rows(rows_01)
    base = assign_tournament_split(records)

    assert assign_tournament_split(list(reversed(records))) == base
    assert assign_tournament_split(records[5:] + records[:5]) == base
