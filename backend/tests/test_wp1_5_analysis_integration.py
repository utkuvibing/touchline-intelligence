"""Executable contracts for the hand-written WP1.5 SQL analysis pack."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from support.db_safety import connect_local

from touchline.ingest.migrate import apply_migrations

DB_URL = os.environ.get("TOUCHLINE_DB_URL")
TEST_SCHEMA = "wp15_analysis_test"
SQL_DIR = Path(__file__).parents[1] / "sql" / "wp1_5"

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


def _seed_analysis_fixture(conn: psycopg.Connection) -> None:
    apply_migrations(conn)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO competitions VALUES (43, 'FIFA World Cup', 'International')")
        cur.execute("INSERT INTO competitions VALUES (44, 'Empty Cup', 'International')")
        cur.execute("INSERT INTO seasons VALUES (106, '2022'), (107, '2023')")
        cur.execute("INSERT INTO competition_seasons VALUES (43, 106), (44, 107)")
        cur.execute("INSERT INTO teams VALUES (1, 'Home'), (2, 'Away'), (3, 'Zero Events')")
        cur.execute("INSERT INTO players VALUES (10, 'Shooter'), (20, 'Listed Only')")
        cur.execute(
            """
            INSERT INTO matches (
                match_id, competition_id, season_id, match_date,
                home_team_id, away_team_id, home_score, away_score
            ) VALUES
                (100, 43, 106, DATE '2022-01-01', 1, 2, 1, 0),
                (101, 43, 106, DATE '2022-01-02', 1, 3, 0, 0)
            """
        )
        cur.execute(
            """
            INSERT INTO match_teams VALUES
                (100, 1, 'home'), (100, 2, 'away'),
                (101, 1, 'home'), (101, 3, 'away')
            """
        )
        cur.execute("INSERT INTO lineups VALUES (100, 1), (100, 2), (101, 1), (101, 3)")
        cur.execute(
            """
            INSERT INTO lineup_memberships (
                match_id, team_id, player_id, player_name, jersey_number
            ) VALUES
                (100, 1, 10, 'Shooter', 9),
                (100, 2, 20, 'Listed Only', 4),
                (101, 1, 10, 'Shooter', 9),
                (101, 3, 20, 'Listed Only', 4)
            """
        )
        cur.execute(
            """
            INSERT INTO lineup_positions (
                match_id, team_id, player_id, source_order, position_id, position_name
            ) VALUES (100, 1, 10, 1, 23, 'Center Forward')
            """
        )
        cur.execute("INSERT INTO possessions VALUES (100, 1, 1), (100, 2, 2), (101, 1, 1)")
        cur.execute(
            """
            INSERT INTO events (
                event_id, match_id, event_index, period, team_id, player_id,
                possession_id, event_type_name, location_x, location_y
            ) VALUES
                ('00000000-0000-0000-0000-000000000001', 100, 1, 1, 1, 10, 1,
                    'Carry', 60, 40),
                ('00000000-0000-0000-0000-000000000002', 100, 2, 1, 1, 10, 1,
                    'Shot', 100, 40),
                ('00000000-0000-0000-0000-000000000003', 100, 3, 1, 2, NULL, 2,
                    'Pass', 40, 40),
                ('00000000-0000-0000-0000-000000000004', 101, 1, 1, 1, 10, 1,
                    'Shot', 95, 35),
                ('00000000-0000-0000-0000-000000000005', 101, 2, 1, 1, 10, NULL,
                    'Shot', 108, 40)
            """
        )
        cur.execute(
            """
            INSERT INTO shots (
                event_id, outcome_id, outcome_name, shot_type_id, shot_type_name
            ) VALUES
                ('00000000-0000-0000-0000-000000000002', 97, 'Goal', 87, 'Open Play'),
                ('00000000-0000-0000-0000-000000000004', 100, 'Saved', 87, 'Open Play'),
                ('00000000-0000-0000-0000-000000000005', 97, 'Goal', 88, 'Penalty')
            """
        )
    conn.commit()


def _queries() -> list[Path]:
    return sorted(SQL_DIR.glob("[0-9][0-9]_*.sql"))


def _run_query(conn: psycopg.Connection, number: int) -> list[tuple[object, ...]]:
    path = _queries()[number - 1]
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(path.read_text(encoding="utf-8"))
        return list(cur.fetchall())


def test_pack_contains_exactly_ten_numbered_queries_and_a_window() -> None:
    queries = _queries()
    assert [path.name[:2] for path in queries] == [f"{number:02}" for number in range(1, 11)]
    assert "lag(event_type_name) OVER" in queries[9].read_text(encoding="utf-8")


def test_all_queries_execute_in_read_only_transactions(conn: psycopg.Connection) -> None:
    _seed_analysis_fixture(conn)

    results = [_run_query(conn, number) for number in range(1, 11)]

    assert len(results[0]) == 2
    assert results[0][0][2:4] == (2, 3)
    assert results[0][1][0:4] == ("Empty Cup", "2023", 0, 0)
    assert results[0][1][4:] == (None, None, 0, 0)
    assert [row[0] for row in results[1]] == [100, 101]
    assert len(results[2]) == 3
    assert results[3] == [(2, 0, 0, 0, 0)]
    assert results[4][0][2:5] == (2, 1, 50.00)
    assert results[5][0][0:4] == (10, "Shooter", 2, 1)
    assert {row[0]: row[1] for row in results[6]} == {"Shot": 3, "Carry": 1, "Pass": 1}
    assert len(results[7]) == 3
    assert results[8][0][2:] == (4, 1, 2, 2)
    assert {row[0]: row[1] for row in results[9]} == {
        "Carry": 1,
        "[first event in possession]": 1,
    }


def test_team_results_preserve_zero_points_for_scored_losses(
    conn: psycopg.Connection,
) -> None:
    _seed_analysis_fixture(conn)

    rows = _run_query(conn, 3)
    by_team = {row[2]: row for row in rows}

    assert by_team["Away"][-1] == 0


def test_lineup_query_does_not_turn_membership_into_appearance_or_minutes() -> None:
    sql = _queries()[8].read_text(encoding="utf-8").lower()

    assert "lineup_memberships" in sql
    assert "appearance" not in sql.split("-- interpretation:", 1)[0]
    assert "minutes_played" not in sql
