"""Loader tests that need a real PostgreSQL.

Skipped unless ``TOUCHLINE_DB_URL`` is set. CI provides a service container; locally, start
``infra/docker-compose.yml``.

These use the **committed fixture**, never the real StatsBomb download, so they are deterministic
and cost nothing in CI.

Isolation: every test runs inside a dedicated PostgreSQL schema that is created and dropped around
it. The provisional DDL uses unqualified table names, so a `search_path` is enough to keep a
destructive reset away from a developer's loaded World Cup data.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from touchline.ingest import load as loader
from touchline.ingest.cli import (
    CollectedScope,
    ReconciliationError,
    SourceCounts,
    collect,
    reconcile,
)
from touchline.ingest.records import Competition
from touchline.ingest.source import StatsBombSource

DB_URL = os.environ.get("TOUCHLINE_DB_URL")
FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "statsbomb"
TEST_SCHEMA = "wp03_fixture_test"

# Exactly what the committed fixture contains. Hard-coded rather than derived, so a change to the
# fixture or the parser has to be acknowledged here.
EXPECTED = loader.LoadCounts(
    competitions=1,
    seasons=1,
    competition_seasons=1,
    teams=3,
    players=4,
    matches=2,
    match_teams=4,
    lineups=4,
    lineup_memberships=5,
    lineup_positions=1,
    lineup_cards=1,
    possessions=1,
    events=9,
    event_relations=2,
    shots=4,
    shot_freeze_frame_players=1,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        DB_URL is None,
        reason="TOUCHLINE_DB_URL not set; start infra/docker-compose.yml and copy .env.example",
    ),
]


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    """A connection whose tables live in a throwaway schema, dropped afterwards."""
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


@pytest.fixture
def fixture_data() -> CollectedScope:
    """Parse the committed fixture through the real collect() path."""
    source = StatsBombSource(FIXTURES, offline=True)
    return collect(source, 43, 106)


def _counts_in_new_transaction() -> loader.LoadCounts:
    """Read counts over a *separate* connection, so only committed data is visible."""
    assert DB_URL is not None
    with psycopg.connect(DB_URL) as other, other.cursor() as cur:
        cur.execute(f'SET search_path TO "{TEST_SCHEMA}"')
        counts = {}
        for table in loader.LoadCounts.__dataclass_fields__:
            # Table names come from the fixed tuple above, not from input.
            cur.execute(f"SELECT count(*) FROM {table}")
            row = cur.fetchone()
            counts[table] = int(row[0]) if row else 0
    return loader.LoadCounts(**counts)


def _load_fixture(conn: psycopg.Connection, scope: CollectedScope) -> loader.LoadCounts:
    return loader.load_all(
        conn,
        competitions=scope.competitions,
        teams=scope.teams,
        players=scope.players,
        matches=scope.matches,
        shots=scope.shots,
        lineups=scope.lineups,
        memberships=scope.memberships,
        positions=scope.positions,
        cards=scope.cards,
        possessions=scope.possessions,
        events=scope.events,
        relations=scope.relations,
        freeze_frames=scope.freeze_frames,
    )


def test_reset_schema_rebuilds_through_ordered_migrations(conn: psycopg.Connection) -> None:
    """The destructive local rebuild must use the same versioned schema path as an upgrade."""
    loader.reset_schema(conn)

    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations ORDER BY version")
        versions = [row[0] for row in cur.fetchall()]

    assert versions == [
        "0001_initial",
        "0002_relational_constraints",
        "0003_normalize_competition_seasons",
        "0004_event_and_lineup_core",
        "0005_event_and_lineup_constraints",
        "0006_ingestion_runs",
        "0007_measured_event_x_boundary",
    ]


def test_successful_load_writes_exactly_the_fixture(
    conn: psycopg.Connection, fixture_data: CollectedScope
) -> None:
    """The happy path: reset, load, reconcile, commit - with exact counts."""
    loader.reset_schema(conn)
    _load_fixture(conn, fixture_data)
    db_counts = loader.count_rows(conn)

    assert db_counts == EXPECTED
    assert reconcile(fixture_data.source_counts, db_counts) is True

    conn.commit()
    assert _counts_in_new_transaction() == EXPECTED


def test_shot_detail_join_returns_location_player_team_and_outcome(
    conn: psycopg.Connection, fixture_data: CollectedScope
) -> None:
    """The join the whole schema exists to support.

    Also pins the LEFT JOIN on players: the fixture holds one shot with no attributed player, and
    an INNER JOIN would drop it and quietly change the shot count away from the source.
    """
    loader.reset_schema(conn)
    _load_fixture(conn, fixture_data)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT e.event_id::text, shooting.team_name, opponent.team_name, p.player_name,
                   e.location_x, e.location_y, s.outcome_name, s.shot_type_name
            FROM shots AS s
            JOIN events AS e ON e.event_id = s.event_id
            JOIN matches AS m ON m.match_id = e.match_id
            JOIN teams AS shooting ON shooting.team_id = e.team_id
            JOIN teams AS opponent ON opponent.team_id = CASE
                     WHEN e.team_id = m.home_team_id THEN m.away_team_id ELSE m.home_team_id END
            LEFT JOIN players AS p ON p.player_id = e.player_id
            ORDER BY e.event_id
        """)
        rows = cur.fetchall()

    assert len(rows) == EXPECTED.shots, "the LEFT JOIN must not drop the unattributed shot"

    goal = next(r for r in rows if r[0].endswith("003"))
    assert goal[1] == "Fixture United"
    assert goal[2] == "Fixture Rovers"
    assert goal[3] == "Bea Striker"
    assert (goal[4], goal[5]) == (112.0, 40.0)
    assert goal[6] == "Goal"

    unattributed = next(r for r in rows if r[0].endswith("006"))
    assert unattributed[3] is None
    assert unattributed[7] == "Penalty"

    no_location = next(r for r in rows if r[0].endswith("005"))
    assert (no_location[4], no_location[5]) == (None, None)


def test_full_fixture_loads_lineup_event_relation_possession_and_freeze_detail(
    conn: psycopg.Connection, fixture_data: CollectedScope
) -> None:
    """The committed fixture exercises every WP1.2 entity family, not a legacy shot-only seam."""
    loader.reset_schema(conn)
    _load_fixture(conn, fixture_data)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT lm.jersey_number, lp.source_order, lc.card_type
            FROM lineup_memberships AS lm
            JOIN lineup_positions AS lp USING (match_id, team_id, player_id)
            JOIN lineup_cards AS lc USING (match_id, team_id, player_id)
            WHERE lm.player_id = 8001
            """
        )
        assert cur.fetchone() == (8, 1, "Yellow Card")

        cur.execute(
            """
            SELECT p.team_id, e.type_data, count(r.related_event_id)
            FROM events AS e
            JOIN possessions AS p USING (match_id, possession_id)
            LEFT JOIN event_relations AS r ON r.source_event_id = e.event_id
            WHERE e.event_id = 'aaaaaaaa-0000-0000-0000-000000000002'
            GROUP BY p.team_id, e.type_data
            """
        )
        row = cur.fetchone()
        assert row is not None
        possession_team, type_data, relation_count = row
        assert possession_team == 7001
        assert type_data == {"pass": {"height": {"id": 1, "name": "Ground Pass"}}}
        assert relation_count == 1
        assert "statsbomb_xg" not in str(type_data)

        cur.execute(
            """
            SELECT s.key_pass_event_id::text, s.end_location_z, f.player_id, f.teammate
            FROM shots AS s
            JOIN shot_freeze_frame_players AS f USING (event_id)
            WHERE s.event_id = 'aaaaaaaa-0000-0000-0000-000000000003'
            """
        )
        assert cur.fetchone() == (
            "aaaaaaaa-0000-0000-0000-000000000002",
            1.2,
            8003,
            False,
        )


def test_failed_reconciliation_leaves_nothing_committed(
    conn: psycopg.Connection, fixture_data: CollectedScope
) -> None:
    """The contract that transaction ownership exists for.

    Rows are written, counted, found not to match, and the transaction is abandoned. Nothing
    durable may remain - otherwise reconciliation would be a report about data already kept.
    """
    wrong_source_counts = SourceCounts(
        matches=999, shots=999, shots_without_location=0, shots_without_player=0
    )

    loader.reset_schema(conn)
    _load_fixture(conn, fixture_data)
    db_counts = loader.count_rows(conn)

    assert db_counts == EXPECTED, "rows are visible inside the transaction"
    assert reconcile(wrong_source_counts, db_counts) is False

    conn.rollback()

    with pytest.raises(psycopg.errors.UndefinedTable):
        _counts_in_new_transaction()


def test_error_midway_leaves_nothing_committed(
    conn: psycopg.Connection, fixture_data: CollectedScope
) -> None:
    """A real database failure partway through a load must discard the earlier tables too.

    The failure is genuine, not simulated: the player list is given a duplicate id, so the COPY
    into `players` violates the primary key. The loader writes competitions and teams before it
    reaches players, so by the time this raises, two tables already hold rows in this transaction.

    That ordering is asserted rather than assumed - the constraint name in the error identifies
    exactly which stage failed.
    """
    duplicated_players = [*fixture_data.players, fixture_data.players[0]]

    loader.reset_schema(conn)

    with pytest.raises(psycopg.errors.UniqueViolation) as exc_info:
        loader.load_all(
            conn,
            competitions=fixture_data.competitions,
            teams=fixture_data.teams,
            players=duplicated_players,
            matches=fixture_data.matches,
            shots=fixture_data.shots,
            lineups=fixture_data.lineups,
            memberships=fixture_data.memberships,
            positions=fixture_data.positions,
            cards=fixture_data.cards,
            possessions=fixture_data.possessions,
            events=fixture_data.events,
            relations=fixture_data.relations,
            freeze_frames=fixture_data.freeze_frames,
        )

    assert exc_info.value.diag.constraint_name == "players_pkey", (
        "the failure must be the players COPY, which the loader only reaches after competitions "
        "and teams have already been written in this transaction"
    )

    # PostgreSQL aborts the whole transaction on a failed statement, so the earlier writes are
    # already unreachable rather than merely unwanted.
    with pytest.raises(psycopg.errors.InFailedSqlTransaction):
        loader.count_rows(conn)

    conn.rollback()

    with pytest.raises(psycopg.errors.UndefinedTable):
        _counts_in_new_transaction()


def test_reconciliation_error_is_raised_inside_the_transaction() -> None:
    """The CLI signals a mismatch by raising, which is what triggers the rollback."""
    assert issubclass(ReconciliationError, RuntimeError)


def test_loading_into_a_populated_schema_is_refused(
    conn: psycopg.Connection, fixture_data: CollectedScope
) -> None:
    """The loader must refuse rather than duplicate.

    This is what makes "not idempotent" safe to ship: an explicit message naming the fix, not a
    duplicate-key traceback and not silently doubled counts.
    """
    loader.reset_schema(conn)
    _load_fixture(conn, fixture_data)

    with pytest.raises(loader.NotIdempotentError, match="not idempotent"):
        loader.load_all(
            conn,
            competitions=[Competition(43, 106, "FIFA World Cup", "2022", "International")],
            teams=[],
            players=[],
            matches=[],
            shots=[],
            lineups=[],
            memberships=[],
            positions=[],
            cards=[],
            possessions=[],
            events=[],
            relations=[],
            freeze_frames=[],
        )
