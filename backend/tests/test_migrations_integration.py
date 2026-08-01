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

    assert versions == [
        "0001_initial",
        "0002_relational_constraints",
        "0003_normalize_competition_seasons",
        "0004_event_and_lineup_core",
        "0005_event_and_lineup_constraints",
    ]


def _seed_valid_parents(conn: psycopg.Connection) -> None:
    apply_migrations(conn)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO competitions VALUES (43, 'FIFA World Cup', 'International')")
        cur.execute("INSERT INTO seasons VALUES (106, '2022')")
        cur.execute("INSERT INTO competition_seasons VALUES (43, 106)")
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
        cur.execute("INSERT INTO match_teams VALUES (100, 1, 'home'), (100, 2, 'away')")


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


def test_shot_detail_fields_remain_nullable(conn: psycopg.Connection) -> None:
    _seed_valid_parents(conn)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO events (event_id, match_id, team_id, event_type_name)
            VALUES ('00000000-0000-0000-0000-000000000010', 100, 1, 'Shot')
            """
        )
        cur.execute("INSERT INTO shots (event_id) VALUES ('00000000-0000-0000-0000-000000000010')")
        cur.execute("SELECT outcome_name, end_location_x, key_pass_event_id FROM shots")
        row = cur.fetchone()

    assert row == (None, None, None)


def test_shot_requires_an_event_and_event_requires_a_match(
    conn: psycopg.Connection,
) -> None:
    """The normalized shot-to-match chain must be unbroken at both foreign keys."""
    apply_migrations(conn)
    missing_event = "00000000-0000-0000-0000-000000000080"
    missing_match_event = "00000000-0000-0000-0000-000000000081"

    with (
        pytest.raises(psycopg.errors.ForeignKeyViolation) as shot_error,
        conn.transaction(),
        conn.cursor() as cur,
    ):
        cur.execute("INSERT INTO shots (event_id) VALUES (%s)", (missing_event,))
    assert shot_error.value.diag.constraint_name == "shots_event_fk"

    with (
        pytest.raises(psycopg.errors.ForeignKeyViolation) as event_error,
        conn.transaction(),
        conn.cursor() as cur,
    ):
        cur.execute(
            "INSERT INTO events (event_id, match_id, event_type_name) VALUES (%s, 999999, 'Pass')",
            (missing_match_event,),
        )
    assert event_error.value.diag.constraint_name == "events_match_fk"


def test_shot_details_and_freeze_actors_require_a_shot_event(
    conn: psycopg.Connection,
) -> None:
    """A generic event cannot be relabelled as a Shot by attaching subtype rows."""
    _seed_valid_parents(conn)
    pass_event = "00000000-0000-0000-0000-000000000091"
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO events (event_id, match_id, event_type_name) VALUES (%s, 100, 'Pass')",
            (pass_event,),
        )

    with (
        pytest.raises(psycopg.errors.ForeignKeyViolation) as shot_error,
        conn.transaction(),
        conn.cursor() as cur,
    ):
        cur.execute("INSERT INTO shots (event_id) VALUES (%s)", (pass_event,))
    assert shot_error.value.diag.constraint_name == "shots_event_fk"

    with (
        pytest.raises(psycopg.errors.ForeignKeyViolation) as freeze_error,
        conn.transaction(),
        conn.cursor() as cur,
    ):
        cur.execute(
            "INSERT INTO shot_freeze_frame_players (event_id, source_order, teammate) "
            "VALUES (%s, 1, true)",
            (pass_event,),
        )
    assert freeze_error.value.diag.constraint_name == "shot_freeze_frame_players_shot_fk"


def test_event_location_boundaries_and_optional_absence(
    conn: psycopg.Connection,
) -> None:
    """Both pitch axes accept their boundaries and an entirely absent location."""
    _seed_valid_parents(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO events (
                event_id, match_id, event_type_name, location_x, location_y
            ) VALUES
                ('00000000-0000-0000-0000-000000000082', 100, 'Pass', 0.0, 0.0),
                ('00000000-0000-0000-0000-000000000083', 100, 'Pass', 120.0, 80.0),
                ('00000000-0000-0000-0000-000000000084', 100, 'Pass', NULL, NULL)
            """
        )
        cur.execute(
            "SELECT location_x, location_y FROM events "
            "WHERE event_id IN ("
            "'00000000-0000-0000-0000-000000000082', "
            "'00000000-0000-0000-0000-000000000083', "
            "'00000000-0000-0000-0000-000000000084') "
            "ORDER BY event_id"
        )
        assert cur.fetchall() == [(0.0, 0.0), (120.0, 80.0), (None, None)]


@pytest.mark.parametrize(
    ("event_id", "location_x", "location_y", "constraint_name"),
    [
        ("00000000-0000-0000-0000-000000000085", -0.01, 40.0, "events_location_x_bounds"),
        ("00000000-0000-0000-0000-000000000086", 120.01, 40.0, "events_location_x_bounds"),
        ("00000000-0000-0000-0000-000000000087", 60.0, -0.01, "events_location_y_bounds"),
        ("00000000-0000-0000-0000-000000000088", 60.0, 80.01, "events_location_y_bounds"),
        ("00000000-0000-0000-0000-000000000089", 60.0, None, "events_location_pair_complete"),
        ("00000000-0000-0000-0000-000000000090", None, 40.0, "events_location_pair_complete"),
    ],
)
def test_event_location_rejects_out_of_bounds_or_unpaired_coordinates(
    conn: psycopg.Connection,
    event_id: str,
    location_x: float | None,
    location_y: float | None,
    constraint_name: str,
) -> None:
    _seed_valid_parents(conn)

    with pytest.raises(psycopg.errors.CheckViolation) as exc_info, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO events "
            "(event_id, match_id, event_type_name, location_x, location_y) "
            "VALUES (%s, 100, 'Pass', %s, %s)",
            (event_id, location_x, location_y),
        )

    assert exc_info.value.diag.constraint_name == constraint_name


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
        cur.execute(
            """
            INSERT INTO shots (
                shot_id, match_id, team_id, period, minute, second, location_x, location_y
            )
            VALUES ('ef2df858-42ca-4e82-86b0-35451be21cdb', 100, 1, 1, 12, 34, 101.5, 42.0)
            """
        )

    apply_migrations(conn)

    with conn.cursor() as cur:
        cur.execute("SELECT event_id::text FROM shots")
        shot_rows = cur.fetchall()
        cur.execute(
            "SELECT event_id::text, event_index, timestamp, possession_id, play_pattern_id, "
            "position_id, duration FROM events"
        )
        event_rows = cur.fetchall()
        cur.execute("SELECT competition_id, competition_name FROM competitions")
        competitions = cur.fetchall()
        cur.execute("SELECT season_id, season_name FROM seasons")
        seasons = cur.fetchall()
        cur.execute("SELECT competition_id, season_id FROM competition_seasons")
        competition_seasons = cur.fetchall()
        cur.execute("SELECT match_id, team_id, role FROM match_teams ORDER BY role")
        match_teams = cur.fetchall()
        cur.execute("SELECT version FROM schema_migrations ORDER BY version")
        versions = [row[0] for row in cur.fetchall()]

    assert shot_rows == [("ef2df858-42ca-4e82-86b0-35451be21cdb",)]
    assert event_rows == [
        ("ef2df858-42ca-4e82-86b0-35451be21cdb", None, None, None, None, None, None)
    ]
    assert competitions == [(43, "FIFA World Cup")]
    assert seasons == [(106, "2022")]
    assert competition_seasons == [(43, 106)]
    assert match_teams == [(100, 2, "away"), (100, 1, "home")]
    assert versions == [
        "0001_initial",
        "0002_relational_constraints",
        "0003_normalize_competition_seasons",
        "0004_event_and_lineup_core",
        "0005_event_and_lineup_constraints",
    ]


def test_populated_0002_schema_upgrades_forward_without_losing_shots(
    conn: psycopg.Connection,
) -> None:
    """Reproduce the populated schema delivered by ef2df858, including its migration ledger."""
    first_two = read_migrations()[:2]
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE schema_migrations (
                version text PRIMARY KEY,
                checksum text NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
                applied_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        for migration in first_two:
            cur.execute(migration.sql)
            cur.execute(
                "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                (migration.version, migration.checksum),
            )
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
        cur.execute(
            """
            INSERT INTO shots (
                shot_id, match_id, team_id, player_id, period, minute, second,
                location_x, location_y, outcome, body_part, technique, shot_type
            ) VALUES (
                '00000000-0000-0000-0000-000000000099', 100, 1, 10, 1, 12, 34,
                101.5, 42.0, 'Goal', 'Right Foot', 'Normal', 'Open Play'
            )
            """
        )

    applied = apply_migrations(conn)

    assert applied == (
        "0003_normalize_competition_seasons",
        "0004_event_and_lineup_core",
        "0005_event_and_lineup_constraints",
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT e.match_id, e.team_id, e.player_id, e.period, e.location_x,
                   s.outcome_name, s.shot_type_name
            FROM shots AS s JOIN events AS e USING (event_id)
            """
        )
        assert cur.fetchone() == (100, 1, 10, 1, 101.5, "Goal", "Open Play")

    assert apply_migrations(conn) == ()


@pytest.mark.parametrize(
    ("statement", "constraint_name"),
    [
        (
            "INSERT INTO events (event_id, match_id, event_type_name, type_data) "
            "VALUES ('0f2df858-42ca-4e82-86b0-35451be21cdb', 100, 'Pass', '[]')",
            "events_type_data_object",
        ),
        (
            "INSERT INTO events (event_id, match_id, event_type_name, type_data) "
            "VALUES ('1f2df858-42ca-4e82-86b0-35451be21cdb', 100, 'Shot', '{\"foo\": 1}')",
            "events_shots_have_no_residual_details",
        ),
        (
            "INSERT INTO events (event_id, match_id, event_type_name, type_data) "
            "VALUES ('5f2df858-42ca-4e82-86b0-35451be21cdb', 100, 'Pass', "
            '\'{"nested": {"statsbomb_xg": 0.42}}\')',
            "events_no_provider_xg",
        ),
        (
            "INSERT INTO shots (event_id) VALUES ('2f2df858-42ca-4e82-86b0-35451be21cdb')",
            "shots_event_fk",
        ),
        (
            "INSERT INTO event_relations (match_id, source_event_id, related_event_id, "
            "source_order) VALUES "
            "(100, '3f2df858-42ca-4e82-86b0-35451be21cdb', "
            "'3f2df858-42ca-4e82-86b0-35451be21cdb', 1)",
            "event_relations_not_self",
        ),
        (
            "INSERT INTO events (event_id, match_id, team_id, event_type_name) "
            "VALUES ('6f2df858-42ca-4e82-86b0-35451be21cdb', 100, 999, 'Pass')",
            "events_match_team_fk",
        ),
        (
            "INSERT INTO possessions (match_id, possession_id, team_id) VALUES (100, 1, 999)",
            "possessions_match_team_fk",
        ),
        (
            "INSERT INTO lineups (match_id, team_id) VALUES (100, 999)",
            "lineups_match_team_fk",
        ),
        (
            "INSERT INTO lineup_memberships "
            "(match_id, team_id, player_id, player_name) VALUES (100, 1, 1, 'P')",
            "lineup_memberships_lineup_fk",
        ),
        (
            "INSERT INTO lineup_positions "
            "(match_id, team_id, player_id, source_order) VALUES (100, 1, 1, 1)",
            "lineup_positions_membership_fk",
        ),
        (
            "INSERT INTO lineup_cards "
            "(match_id, team_id, player_id, source_order, card_type) "
            "VALUES (100, 1, 1, 1, 'Yellow Card')",
            "lineup_cards_membership_fk",
        ),
        (
            "INSERT INTO event_relations "
            "(match_id, source_event_id, related_event_id, source_order) VALUES "
            "(100, '8f2df858-42ca-4e82-86b0-35451be21cdb', "
            "'9f2df858-42ca-4e82-86b0-35451be21cdb', 1)",
            "event_relations_source_event_fk",
        ),
        (
            "INSERT INTO shot_freeze_frame_players (event_id, source_order, teammate) "
            "VALUES ('7f2df858-42ca-4e82-86b0-35451be21cdb', 0, true)",
            "shot_freeze_frame_players_source_order_positive",
        ),
    ],
)
def test_event_layer_rejects_invalid_rows(
    conn: psycopg.Connection, statement: str, constraint_name: str
) -> None:
    _seed_valid_parents(conn)

    with pytest.raises(psycopg.errors.IntegrityError) as exc_info, conn.cursor() as cur:
        cur.execute(statement)

    assert exc_info.value.diag.constraint_name == constraint_name


def test_event_relation_order_is_directed_and_event_indexes_are_match_unique(
    conn: psycopg.Connection,
) -> None:
    _seed_valid_parents(conn)
    first = "00000000-0000-0000-0000-000000000011"
    second = "00000000-0000-0000-0000-000000000012"
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO events (event_id, match_id, event_index, event_type_name) "
            "VALUES (%s, 100, 1, 'Pass'), (%s, 100, 2, 'Pass')",
            (first, second),
        )
        cur.execute(
            "INSERT INTO event_relations (match_id, source_event_id, related_event_id, "
            "source_order) "
            "VALUES (100, %s, %s, 1), (100, %s, %s, 1)",
            (first, second, second, first),
        )

    with pytest.raises(psycopg.errors.IntegrityError) as exc_info, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO events (event_id, match_id, event_index, event_type_name) "
            "VALUES ('00000000-0000-0000-0000-000000000013', 100, 1, 'Pass')"
        )
    assert exc_info.value.diag.constraint_name == "events_match_index_unique"


def test_shot_and_freeze_detail_constraints_apply_after_their_event_exists(
    conn: psycopg.Connection,
) -> None:
    _seed_valid_parents(conn)
    event_id = "00000000-0000-0000-0000-000000000014"
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO events (event_id, match_id, event_type_name) VALUES (%s, 100, 'Shot')",
            (event_id,),
        )

    with (
        pytest.raises(psycopg.errors.IntegrityError) as shot_error,
        conn.transaction(),
        conn.cursor() as cur,
    ):
        cur.execute("INSERT INTO shots (event_id, end_location_x) VALUES (%s, 100.0)", (event_id,))
    assert shot_error.value.diag.constraint_name == "shots_end_location_pair_complete"

    with (
        pytest.raises(psycopg.errors.IntegrityError) as freeze_error,
        conn.transaction(),
        conn.cursor() as cur,
    ):
        cur.execute(
            "INSERT INTO shot_freeze_frame_players (event_id, source_order, teammate) "
            "VALUES (%s, 0, true)",
            (event_id,),
        )
    assert (
        freeze_error.value.diag.constraint_name == "shot_freeze_frame_players_source_order_positive"
    )


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
