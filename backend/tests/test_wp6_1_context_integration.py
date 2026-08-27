"""Database-backed chronology regression for the WP6.1 target-free context loader."""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
import pytest
from support.db_safety import connect_local

from touchline.ingest.migrate import apply_migrations
from touchline.modeling.v2_folds import load_gate_config
from touchline.modeling.wp6_1_context import load_v2_contexts

DB_URL = os.environ.get("TOUCHLINE_DB_URL")
TEST_SCHEMA = "wp61_context_test"

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


def _seed_score_chronology(conn: psycopg.Connection) -> None:
    apply_migrations(conn)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO competitions VALUES (43, 'World Cup', 'International')")
        cur.execute("INSERT INTO seasons VALUES (3, '2018')")
        cur.execute("INSERT INTO competition_seasons VALUES (43, 3)")
        cur.execute("INSERT INTO teams VALUES (1, 'Home'), (2, 'Away')")
        cur.execute("INSERT INTO players VALUES (10, 'Shooter')")
        cur.execute(
            """
            INSERT INTO matches (
                match_id, competition_id, season_id, match_date,
                home_team_id, away_team_id, home_score, away_score
            ) VALUES (100, 43, 3, DATE '2018-06-01', 1, 2, 1, 0)
            """
        )
        cur.execute("INSERT INTO match_teams VALUES (100, 1, 'home'), (100, 2, 'away')")
        for index in (1, 2, 3):
            cur.execute(
                """
                INSERT INTO events (
                    event_id, match_id, event_index, period, timestamp, minute, second,
                    team_id, player_id, event_type_name, location_x, location_y,
                    play_pattern_id, play_pattern_name
                ) VALUES (
                    %s::uuid, 100, %s, 1, %s::interval, %s, 0,
                    1, 10, 'Shot', 100.0, 40.0, 1, 'Regular Play'
                )
                """,
                (f"00000000-0000-0000-0000-{index:012d}", index, f"00:0{index}:00", index),
            )
            cur.execute(
                """
                INSERT INTO shots (
                    event_id, outcome_id, outcome_name, body_part_id, body_part_name,
                    technique_id, technique_name, shot_type_id, shot_type_name
                ) VALUES (%s::uuid, %s, %s, 40, 'Right Foot', 93, 'Normal', 87, 'Open Play')
                """,
                (
                    f"00000000-0000-0000-0000-{index:012d}",
                    97 if index == 2 else 96,
                    "Goal" if index == 2 else "Saved",
                ),
            )
    conn.commit()


def test_pre_shot_score_changes_only_after_an_earlier_scoring_event(
    conn: psycopg.Connection,
) -> None:
    _seed_score_chronology(conn)

    contexts = load_v2_contexts(conn, load_gate_config())
    by_index = {item.metadata.event_index: item.context for item in contexts}

    assert (by_index[1].team_score_before, by_index[1].opponent_score_before) == (0, 0)
    assert (by_index[2].team_score_before, by_index[2].opponent_score_before) == (0, 0)
    assert (by_index[3].team_score_before, by_index[3].opponent_score_before) == (1, 0)
