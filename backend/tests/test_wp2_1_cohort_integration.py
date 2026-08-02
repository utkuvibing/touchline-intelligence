"""Executable contracts for the WP2.1 cohort and leakage boundary."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from touchline.ingest.migrate import apply_migrations

DB_URL = os.environ.get("TOUCHLINE_DB_URL")
TEST_SCHEMA = "wp21_cohort_test"
SQL_DIR = Path(__file__).parents[1] / "sql" / "wp2_1"
CONTRACT = (
    Path(__file__).parents[2] / "docs" / "modeling" / ("wp2_1-cohort-and-leakage-contract.md")
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(DB_URL is None, reason="TOUCHLINE_DB_URL is not set"),
]


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    assert DB_URL is not None
    with psycopg.connect(DB_URL) as connection:
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


def _seed_cohort_fixture(conn: psycopg.Connection) -> None:
    apply_migrations(conn)
    with conn.cursor() as cur:
        # The production constraint rejects half-missing coordinate pairs. Drop it only in this
        # adversarial fixture so each SQL predicate is independently observable by mutation tests.
        cur.execute("ALTER TABLE events DROP CONSTRAINT events_location_pair_complete")
        cur.execute(
            "INSERT INTO competitions VALUES "
            "(43, 'World Cup', 'International'), (99, 'Outside', 'Test')"
        )
        cur.execute("INSERT INTO seasons VALUES (3, '2018'), (1, 'Outside')")
        cur.execute("INSERT INTO competition_seasons VALUES (43, 3), (99, 1)")
        cur.execute("INSERT INTO teams VALUES (1, 'Home'), (2, 'Away')")
        cur.execute("INSERT INTO players VALUES (10, 'Shooter')")
        cur.execute(
            """
            INSERT INTO matches (
                match_id, competition_id, season_id, match_date,
                home_team_id, away_team_id, home_score, away_score
            ) VALUES
                (100, 43, 3, DATE '2018-06-01', 1, 2, 1, 0),
                (900, 99, 1, DATE '2018-06-02', 1, 2, 1, 0)
            """
        )
        cur.execute(
            "INSERT INTO match_teams VALUES "
            "(100, 1, 'home'), (100, 2, 'away'), (900, 1, 'home'), (900, 2, 'away')"
        )
        events = [
            (1, 100, 1, 1, 10, 100.0, 40.0, "Shot"),
            (2, 100, 2, 1, 10, 95.0, 35.0, "Shot"),
            (3, 100, 3, 1, 10, 108.0, 40.0, "Shot"),
            (4, 100, 4, 5, 10, 108.0, 40.0, "Shot"),
            (5, 100, 5, 5, 10, 105.0, 38.0, "Shot"),
            (6, 100, 6, 1, 10, 90.0, 30.0, "Shot"),
            (7, 100, 7, 1, 10, 90.0, 31.0, "Shot"),
            (8, 900, 1, 1, 10, 110.0, 40.0, "Shot"),
            (9, 100, 8, 1, 10, 110.0, 40.0, "Own Goal For"),
            (10, 100, 9, 1, 10, 110.0, 40.0, "Own Goal Against"),
            (11, 100, 10, 1, 10, None, None, "Shot"),
            (12, 100, 11, 1, None, 91.0, 31.0, "Shot"),
            (13, 100, 12, 1, 10, 92.0, 32.0, "Shot"),
            (14, 100, 13, 1, 10, 93.0, 33.0, "Shot"),
            (15, 100, 14, None, 10, 94.0, 34.0, "Shot"),
            (16, 100, 15, 1, 10, None, 35.0, "Shot"),
            (17, 100, 16, 1, 10, 95.0, None, "Shot"),
        ]
        for number, match_id, index, period, player_id, x, y, event_type in events:
            cur.execute(
                """
                INSERT INTO events (
                    event_id, match_id, event_index, period, team_id, player_id,
                    event_type_name, location_x, location_y, play_pattern_id, play_pattern_name
                ) VALUES (
                    %s::uuid, %s, %s, %s, 1, %s, %s, %s, %s, 1, 'Regular Play'
                )
                """,
                (
                    f"00000000-0000-0000-0000-{number:012d}",
                    match_id,
                    index,
                    period,
                    player_id,
                    event_type,
                    x,
                    y,
                ),
            )

        shot_rows = {
            1: (97, "Goal", 40, "Right Foot", 93, "Normal", 87, "Open Play"),
            2: (96, "Saved", 38, "Left Foot", 93, "Normal", 87, "Open Play"),
            3: (97, "Goal", 40, "Right Foot", 93, "Normal", 88, "Penalty"),
            4: (96, "Saved", 40, "Right Foot", 93, "Normal", 88, "Penalty"),
            5: (97, "Goal", 40, "Right Foot", 93, "Normal", 87, "Open Play"),
            6: (None, None, 40, "Right Foot", 93, "Normal", 87, "Open Play"),
            7: (96, "Saved", None, None, 93, "Normal", 87, "Open Play"),
            8: (97, "Goal", 40, "Right Foot", 93, "Normal", 87, "Open Play"),
            11: (96, "Saved", 40, "Right Foot", 93, "Normal", 87, "Open Play"),
            12: (96, "Saved", 40, "Right Foot", 93, "Normal", 87, "Open Play"),
            13: (96, "Saved", 40, "Right Foot", None, None, 87, "Open Play"),
            14: (96, "Saved", 40, "Right Foot", 93, "Normal", None, None),
            15: (96, "Saved", 40, "Right Foot", 93, "Normal", 87, "Open Play"),
            16: (96, "Saved", 40, "Right Foot", 93, "Normal", 87, "Open Play"),
            17: (96, "Saved", 40, "Right Foot", 93, "Normal", 87, "Open Play"),
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


def test_cohort_is_one_eligible_non_penalty_row_per_shot(conn: psycopg.Connection) -> None:
    _seed_cohort_fixture(conn)

    columns, rows = _run_query(conn, 1)

    assert [str(row[0])[-12:] for row in rows] == ["000000000001", "000000000002"]
    assert [row[-1] for row in rows] == [1, 0]
    assert len({row[0] for row in rows}) == len(rows)
    assert "match_id" in columns
    assert "match_date" in columns
    assert "is_goal" in columns


def test_cohort_projection_exposes_no_forbidden_input_columns(
    conn: psycopg.Connection,
) -> None:
    _seed_cohort_fixture(conn)

    columns, _ = _run_query(conn, 1)

    assert columns == [
        "shot_id",
        "match_id",
        "match_date",
        "competition_id",
        "season_id",
        "event_index",
        "period",
        "minute",
        "second",
        "team_id",
        "player_id",
        "possession_id",
        "raw_location_x",
        "raw_location_y",
        "play_pattern_id",
        "play_pattern_name",
        "under_pressure",
        "body_part_id",
        "body_part_name",
        "technique_id",
        "technique_name",
        "shot_type_id",
        "shot_type_name",
        "aerial_won",
        "follows_dribble",
        "first_time",
        "open_goal",
        "one_on_one",
        "is_goal",
    ]


def test_cohort_keeps_every_required_null_exclusion_explicit() -> None:
    sql = (SQL_DIR / "01_model_shot_cohort.sql").read_text(encoding="utf-8")

    for predicate in (
        "e.player_id IS NOT NULL",
        "e.period IS NOT NULL",
        "e.location_x IS NOT NULL",
        "e.location_y IS NOT NULL",
        "s.outcome_name IS NOT NULL",
        "s.body_part_name IS NOT NULL",
        "s.technique_name IS NOT NULL",
        "s.shot_type_name IS NOT NULL",
    ):
        assert sql.count(predicate) == 1


def test_reconciliation_keeps_penalties_missingness_and_own_goals_visible(
    conn: psycopg.Connection,
) -> None:
    _seed_cohort_fixture(conn)

    _, rows = _run_query(conn, 2)
    assert all(isinstance(metric, str) and isinstance(value, int) for metric, value in rows)
    metrics = {
        metric: value
        for metric, value in rows
        if isinstance(metric, str) and isinstance(value, int)
    }

    assert metrics["typed_shots"] == 14
    assert metrics["eligible_non_penalty_shots"] == 2
    assert metrics["eligible_goals"] == 1
    assert metrics["regulation_penalties"] == 1
    assert metrics["shootout_penalties"] == 1
    assert metrics["period_five_non_penalties"] == 1
    assert metrics["missing_player"] == 1
    assert metrics["missing_period"] == 1
    assert metrics["missing_location_pair"] == 3
    assert metrics["missing_outcome"] == 1
    assert metrics["missing_body_part"] == 1
    assert metrics["missing_technique"] == 1
    assert metrics["missing_shot_type"] == 1
    assert metrics["own_goal_for_events"] == 1
    assert metrics["own_goal_against_events"] == 1


def test_category_coverage_has_support_only_and_no_target_aggregates(
    conn: psycopg.Connection,
) -> None:
    _seed_cohort_fixture(conn)

    columns, rows = _run_query(conn, 3)

    assert columns == ["field_name", "observed_value", "shots"]
    assert set(rows) == {
        ("body_part_name", "Left Foot", 1),
        ("body_part_name", "Right Foot", 1),
        ("play_pattern_name", "Regular Play", 2),
        ("shot_type_name", "Open Play", 2),
        ("technique_name", "Normal", 2),
    }


def test_penalty_breakdown_is_reproducible_by_tournament(conn: psycopg.Connection) -> None:
    _seed_cohort_fixture(conn)

    columns, rows = _run_query(conn, 4)

    assert columns[-3:] == [
        "regulation_penalties",
        "shootout_penalties",
        "period_five_non_penalties",
    ]
    assert rows == [(43, 3, "World Cup", "2018", 1, 1, 1)]


def _availability_statuses(contract: str) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for line in contract.splitlines():
        if not line.startswith("|") or "---" in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 3 or cells[0] == "Candidate or field":
            continue
        assert cells[0] not in statuses
        statuses[cells[0]] = cells[1]
    return statuses


def test_every_candidate_has_the_exact_availability_decision() -> None:
    contract = CONTRACT.read_text(encoding="utf-8")
    sql = (SQL_DIR / "01_model_shot_cohort.sql").read_text(encoding="utf-8")
    statuses = _availability_statuses(contract)

    assert statuses == {
        "Raw shot `location_x`, `location_y`": "Available",
        "Body part ID/name": "Available",
        "Technique ID/name": "Available",
        "Shot type ID/name": "Available",
        "Play pattern ID/name": "Available",
        "Period, minute, second": "Available",
        "Team, player, possession IDs": "Available",
        "Competition, season, match ID/date": "Available",
        "`under_pressure`": "Uncertain",
        "`aerial_won`": "Uncertain",
        "`first_time`": "Uncertain",
        "`follows_dribble`": "Uncertain",
        "`open_goal`": "Uncertain",
        "`one_on_one`": "Uncertain",
        "Key-pass event and event relations": "Uncertain",
        "Embedded shot freeze-frame players": "Uncertain",
        "Event position": "Uncertain",
        "Outcome ID/name": "Unavailable",
        "Shot end `x/y/z`": "Unavailable",
        "`deflected`, `redirect`": "Unavailable",
        "`saved_off_target`, `saved_to_post`": "Unavailable",
        "Event duration, `out`": "Unavailable",
        "Provider `statsbomb_xg`": "Unavailable",
        "Future events, final score, later match state": "Unavailable",
        "Target-derived aggregates": "Unavailable",
    }
    assert "statsbomb_xg" not in sql
