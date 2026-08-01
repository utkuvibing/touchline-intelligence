"""Ordered-migration contracts exercised against a real PostgreSQL schema."""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
import pytest

from touchline.ingest.migrate import MigrationDriftError, apply_migrations, read_migrations

DB_URL = os.environ.get("TOUCHLINE_DB_URL")
TEST_SCHEMA = "wp12_migrations_test"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        DB_URL is None,
        reason="TOUCHLINE_DB_URL not set; start infra/docker-compose.yml and copy .env.example",
    ),
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


def test_migrations_apply_in_order_and_a_rerun_is_a_no_op(
    conn: psycopg.Connection,
) -> None:
    apply_migrations(conn)
    apply_migrations(conn)

    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations ORDER BY version")
        versions = [row[0] for row in cur.fetchall()]

    assert versions == ["0001_initial", "0002_relational_constraints"]


def _seed_valid_parents(conn: psycopg.Connection) -> None:
    apply_migrations(conn)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO competitions VALUES (43, 106, 'FIFA World Cup', '2022', 'International')"
        )
        cur.execute("INSERT INTO teams VALUES (1, 'Home'), (2, 'Away')")
        cur.execute("INSERT INTO players VALUES (10, 'Shot Taker')")
        cur.execute(
            """
            INSERT INTO matches (
                match_id, competition_id, season_id, home_team_id, away_team_id,
                home_score, away_score
            ) VALUES (100, 43, 106, 1, 2, 1, 0)
            """
        )


@pytest.mark.parametrize(
    ("statement", "constraint_name"),
    [
        (
            "INSERT INTO teams VALUES (1, 'Duplicate source id')",
            "teams_pkey",
        ),
        (
            """
            INSERT INTO matches (
                match_id, competition_id, season_id, home_team_id, away_team_id
            ) VALUES (101, 999, 999, 1, 2)
            """,
            "matches_competition_fk",
        ),
        (
            """
            INSERT INTO matches (
                match_id, competition_id, season_id, home_team_id, away_team_id
            ) VALUES (101, 43, 106, 999, 2)
            """,
            "matches_home_team_fk",
        ),
        (
            """
            INSERT INTO matches (
                match_id, competition_id, season_id, home_team_id, away_team_id
            ) VALUES (101, 43, 106, 1, 999)
            """,
            "matches_away_team_fk",
        ),
        (
            """
            INSERT INTO matches (
                match_id, competition_id, season_id, home_team_id, away_team_id
            ) VALUES (101, 43, 106, 1, 1)
            """,
            "matches_distinct_teams",
        ),
        (
            """
            INSERT INTO matches (
                match_id, competition_id, season_id, home_team_id, away_team_id,
                home_score, away_score
            ) VALUES (101, 43, 106, 1, 2, -1, 0)
            """,
            "matches_scores_nonnegative",
        ),
        (
            """
            INSERT INTO matches (
                match_id, competition_id, season_id, home_team_id, away_team_id,
                home_score, away_score
            ) VALUES (101, 43, 106, 1, 2, 0, -1)
            """,
            "matches_away_score_nonnegative",
        ),
        (
            """
            INSERT INTO matches (
                match_id, competition_id, season_id, home_team_id, away_team_id,
                home_score, away_score
            ) VALUES (101, 43, 106, 1, 2, 1, NULL)
            """,
            "matches_score_pair_complete",
        ),
        (
            "INSERT INTO shots (shot_id, match_id, team_id) VALUES ('orphan', 999, 1)",
            "shots_match_fk",
        ),
        (
            "INSERT INTO shots (shot_id, match_id, team_id) VALUES ('orphan', 100, 999)",
            "shots_team_fk",
        ),
        (
            """
            INSERT INTO shots (shot_id, match_id, team_id, player_id)
            VALUES ('orphan', 100, 1, 999)
            """,
            "shots_player_fk",
        ),
        (
            "INSERT INTO shots (shot_id, match_id, team_id, period) VALUES ('bad', 100, 1, 6)",
            "shots_period_valid",
        ),
        (
            "INSERT INTO shots (shot_id, match_id, team_id) VALUES ('   ', 100, 1)",
            "shots_id_not_blank",
        ),
        (
            "INSERT INTO shots (shot_id, match_id, team_id, minute) VALUES ('bad', 100, 1, -1)",
            "shots_minute_nonnegative",
        ),
        (
            "INSERT INTO shots (shot_id, match_id, team_id, second) VALUES ('bad', 100, 1, 60)",
            "shots_second_valid",
        ),
        (
            """
            INSERT INTO shots (shot_id, match_id, team_id, location_x, location_y)
            VALUES ('bad', 100, 1, 100.0, NULL)
            """,
            "shots_location_pair_complete",
        ),
        (
            """
            INSERT INTO shots (shot_id, match_id, team_id, location_x, location_y)
            VALUES ('bad', 100, 1, 120.1, 40.0)
            """,
            "shots_location_x_bounds",
        ),
        (
            """
            INSERT INTO shots (shot_id, match_id, team_id, location_x, location_y)
            VALUES ('bad', 100, 1, 100.0, 80.1)
            """,
            "shots_location_y_bounds",
        ),
    ],
)
def test_database_rejects_invalid_relational_rows(
    conn: psycopg.Connection,
    statement: str,
    constraint_name: str,
) -> None:
    _seed_valid_parents(conn)

    with pytest.raises(psycopg.errors.IntegrityError) as exc_info, conn.cursor() as cur:
        cur.execute(statement)

    assert exc_info.value.diag.constraint_name == constraint_name


def test_optional_shot_fields_remain_nullable(conn: psycopg.Connection) -> None:
    _seed_valid_parents(conn)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO shots (shot_id, match_id, team_id, player_id, location_x, location_y)
            VALUES ('nullable-source-condition', 100, 1, NULL, NULL, NULL)
            """
        )
        cur.execute("SELECT player_id, location_x, location_y FROM shots")
        row = cur.fetchone()

    assert row == (None, None, None)


def test_unversioned_m0_schema_is_upgraded_without_losing_rows(
    conn: psycopg.Connection,
) -> None:
    initial = read_migrations()[0]
    with conn.cursor() as cur:
        cur.execute(initial.sql)
        cur.execute(
            "INSERT INTO competitions VALUES (43, 106, 'FIFA World Cup', '2022', 'International')"
        )
        cur.execute("INSERT INTO teams VALUES (1, 'Home'), (2, 'Away')")
        cur.execute(
            """
            INSERT INTO matches (
                match_id, competition_id, season_id, home_team_id, away_team_id,
                home_score, away_score
            ) VALUES (100, 43, 106, 1, 2, 1, 0)
            """
        )
        cur.execute("INSERT INTO shots (shot_id, match_id, team_id) VALUES ('kept', 100, 1)")

    apply_migrations(conn)

    with conn.cursor() as cur:
        cur.execute("SELECT shot_id FROM shots")
        shot_ids = [row[0] for row in cur.fetchall()]
        cur.execute("SELECT version FROM schema_migrations ORDER BY version")
        versions = [row[0] for row in cur.fetchall()]

    assert shot_ids == ["kept"]
    assert versions == ["0001_initial", "0002_relational_constraints"]


def test_applied_migration_checksum_drift_is_rejected(
    conn: psycopg.Connection,
) -> None:
    apply_migrations(conn)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE schema_migrations SET checksum = %s WHERE version = '0001_initial'",
            ("0" * 64,),
        )

    with pytest.raises(MigrationDriftError, match="0001_initial has changed"):
        apply_migrations(conn)


def test_applied_migration_versions_must_be_an_exact_prefix(
    conn: psycopg.Connection,
) -> None:
    apply_migrations(conn)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM schema_migrations WHERE version = '0001_initial'")

    with pytest.raises(MigrationDriftError, match="exact ordered prefix"):
        apply_migrations(conn)


def test_unversioned_m0_schema_drift_is_rejected_before_adoption(
    conn: psycopg.Connection,
) -> None:
    initial = read_migrations()[0]
    with conn.cursor() as cur:
        cur.execute(initial.sql)
        cur.execute("ALTER TABLE players ALTER COLUMN player_name DROP NOT NULL")

    with pytest.raises(MigrationDriftError, match="unversioned M0 schema does not match"):
        apply_migrations(conn)

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM schema_migrations")
        row = cur.fetchone()
    assert row == (0,)
