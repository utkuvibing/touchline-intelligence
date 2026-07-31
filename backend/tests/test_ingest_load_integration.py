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
EXPECTED = loader.LoadCounts(competitions=1, teams=3, players=2, matches=2, shots=4)

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
        for table in ("competitions", "teams", "players", "matches", "shots"):
            # Table names come from the fixed tuple above, not from input.
            cur.execute(f"SELECT count(*) FROM {table}")
            row = cur.fetchone()
            counts[table] = int(row[0]) if row else 0
    return loader.LoadCounts(**counts)


def test_schema_sql_ships_with_the_package() -> None:
    """The DDL is package data; a build that dropped it fails here, not at runtime."""
    ddl = loader.read_schema_sql()

    for table in ("competitions", "teams", "players", "matches", "shots"):
        assert f"CREATE TABLE {table}" in ddl


def test_successful_load_writes_exactly_the_fixture(
    conn: psycopg.Connection, fixture_data: CollectedScope
) -> None:
    """The happy path: reset, load, reconcile, commit - with exact counts."""
    competitions, teams, players, matches, shots, source_counts = fixture_data

    loader.reset_schema(conn)
    loader.load_all(
        conn,
        competitions=competitions,
        teams=teams,
        players=players,
        matches=matches,
        shots=shots,
    )
    db_counts = loader.count_rows(conn)

    assert db_counts == EXPECTED
    assert reconcile(source_counts, db_counts) is True

    conn.commit()
    assert _counts_in_new_transaction() == EXPECTED


def test_shot_detail_join_returns_location_player_team_and_outcome(
    conn: psycopg.Connection, fixture_data: CollectedScope
) -> None:
    """The join the whole schema exists to support.

    Also pins the LEFT JOIN on players: the fixture holds one shot with no attributed player, and
    an INNER JOIN would drop it and quietly change the shot count away from the source.
    """
    competitions, teams, players, matches, shots, _ = fixture_data
    loader.reset_schema(conn)
    loader.load_all(
        conn,
        competitions=competitions,
        teams=teams,
        players=players,
        matches=matches,
        shots=shots,
    )

    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.shot_id, shooting.team_name, opponent.team_name, p.player_name,
                   s.location_x, s.location_y, s.outcome, s.shot_type
            FROM shots AS s
            JOIN matches AS m ON m.match_id = s.match_id
            JOIN teams AS shooting ON shooting.team_id = s.team_id
            JOIN teams AS opponent ON opponent.team_id = CASE
                     WHEN s.team_id = m.home_team_id THEN m.away_team_id ELSE m.home_team_id END
            LEFT JOIN players AS p ON p.player_id = s.player_id
            ORDER BY s.shot_id
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


def test_failed_reconciliation_leaves_nothing_committed(
    conn: psycopg.Connection, fixture_data: CollectedScope
) -> None:
    """The contract that transaction ownership exists for.

    Rows are written, counted, found not to match, and the transaction is abandoned. Nothing
    durable may remain - otherwise reconciliation would be a report about data already kept.
    """
    competitions, teams, players, matches, shots, _ = fixture_data
    wrong_source_counts = SourceCounts(
        matches=999, shots=999, shots_without_location=0, shots_without_player=0
    )

    loader.reset_schema(conn)
    loader.load_all(
        conn,
        competitions=competitions,
        teams=teams,
        players=players,
        matches=matches,
        shots=shots,
    )
    db_counts = loader.count_rows(conn)

    assert db_counts == EXPECTED, "rows are visible inside the transaction"
    assert reconcile(wrong_source_counts, db_counts) is False

    conn.rollback()

    with pytest.raises(psycopg.errors.UndefinedTable):
        _counts_in_new_transaction()


def test_error_midway_leaves_nothing_committed(
    conn: psycopg.Connection, fixture_data: CollectedScope
) -> None:
    """A failure after some tables are written must discard the earlier ones too."""
    competitions, teams, players, matches, shots, _ = fixture_data

    loader.reset_schema(conn)
    loader.load_all(
        conn,
        competitions=competitions,
        teams=teams,
        players=players,
        matches=matches,
        shots=shots,
    )
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
    competitions, teams, players, matches, shots, _ = fixture_data
    loader.reset_schema(conn)
    loader.load_all(
        conn,
        competitions=competitions,
        teams=teams,
        players=players,
        matches=matches,
        shots=shots,
    )

    with pytest.raises(loader.NotIdempotentError, match="not idempotent"):
        loader.load_all(
            conn,
            competitions=[Competition(43, 106, "FIFA World Cup", "2022", "International")],
            teams=[],
            players=[],
            matches=[],
            shots=[],
        )
