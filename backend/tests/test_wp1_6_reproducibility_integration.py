"""WP1.6 clean-rebuild proof using only the committed fictional fixture.

This deliberately uses the production migration runner, production cohort runner and independent
quality seam.  It never invokes the network and never requires the large cached source.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest

from touchline.ingest.cli import SourceCounts
from touchline.ingest.migrate import apply_migrations, read_migrations
from touchline.ingest.run import run_ingestion
from touchline.ingest.source import SOURCE_COMMIT, StatsBombSource
from touchline.quality import inspect

DB_URL = os.environ.get("TOUCHLINE_DB_URL")
FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "statsbomb"
TEST_SCHEMA = "wp16_clean_rebuild"
FIXTURE_SCOPE = ((43, 106),)

# These fields identify a particular invocation or record its wall-clock execution. They are the
# complete declared exclusion set for the canonical snapshot; all other manifest fields compare.
VOLATILE_FIELDS = {
    "ingestion_runs": (
        "run_id",
        "owner_token",
        "started_at",
        "phase_updated_at",
        "finished_at",
        "owner_host",
        "owner_pid",
    ),
    "ingestion_run_scopes": ("run_id",),
    "schema_migrations": ("applied_at",),
}

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        DB_URL is None,
        reason="TOUCHLINE_DB_URL not set; start infra/docker-compose.yml and copy .env.example",
    ),
]


@pytest.fixture
def connection_factory() -> Iterator[Callable[[], psycopg.Connection]]:
    """Give the proof an empty, disposable schema and no access to loaded developer data."""
    assert DB_URL is not None
    with psycopg.connect(DB_URL) as setup, setup.cursor() as cur:
        cur.execute(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE')
        cur.execute(f'CREATE SCHEMA "{TEST_SCHEMA}"')
        setup.commit()

    def factory() -> psycopg.Connection:
        assert DB_URL is not None
        connection = psycopg.connect(DB_URL)
        with connection.cursor() as cur:
            cur.execute(f'SET search_path TO "{TEST_SCHEMA}"')
        connection.commit()
        return connection

    try:
        yield factory
    finally:
        with psycopg.connect(DB_URL) as cleanup, cleanup.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE')
            cleanup.commit()


def _prepare_empty_schema(factory: Callable[[], psycopg.Connection]) -> None:
    """Start one phase from no tables and apply the packaged production migrations."""
    with factory() as conn:
        applied = apply_migrations(conn)
        conn.commit()
    assert applied == tuple(migration.version for migration in read_migrations())


def _clean_schema(factory: Callable[[], psycopg.Connection]) -> None:
    with factory() as conn, conn.cursor() as cur:
        cur.execute(f'DROP SCHEMA "{TEST_SCHEMA}" CASCADE')
        cur.execute(f'CREATE SCHEMA "{TEST_SCHEMA}"')
        conn.commit()


def _canonical_snapshot(factory: Callable[[], psycopg.Connection]) -> dict[str, Any]:
    """Return source facts plus every nonvolatile manifest and migration field."""
    tables = (
        "competitions",
        "seasons",
        "competition_seasons",
        "teams",
        "players",
        "matches",
        "match_teams",
        "lineups",
        "lineup_memberships",
        "lineup_positions",
        "lineup_cards",
        "possessions",
        "events",
        "event_relations",
        "shots",
        "shot_freeze_frame_players",
    )
    with factory() as conn, conn.cursor() as cur:
        snapshot: dict[str, Any] = {}
        for table in tables:
            cur.execute(
                f"SELECT to_jsonb(item)::text FROM {table} AS item ORDER BY to_jsonb(item)::text"
            )
            snapshot[table] = [str(value) for (value,) in cur.fetchall()]
        cur.execute(
            "SELECT (to_jsonb(item) - %s::text[])::text FROM ingestion_runs AS item "
            "ORDER BY (to_jsonb(item) - %s::text[])::text",
            (list(VOLATILE_FIELDS["ingestion_runs"]),) * 2,
        )
        snapshot["ingestion_runs"] = [str(value) for (value,) in cur.fetchall()]
        cur.execute(
            "SELECT jsonb_build_object("
            "'competition_id', competition_id, 'season_id', season_id)::text "
            "FROM ingestion_run_scopes ORDER BY competition_id, season_id"
        )
        snapshot["ingestion_run_scopes"] = [str(value) for (value,) in cur.fetchall()]
        cur.execute(
            "SELECT (to_jsonb(item) - %s::text[])::text FROM schema_migrations AS item "
            "ORDER BY version",
            (list(VOLATILE_FIELDS["schema_migrations"]),),
        )
        snapshot["schema_migrations"] = [str(value) for (value,) in cur.fetchall()]
    return snapshot


def _quality_evidence(factory: Callable[[], psycopg.Connection]) -> dict[str, Any]:
    """Run the audit on a distinct committed-read connection, outside production ingestion."""
    with factory() as conn:
        report = inspect(conn, FIXTURE_SCOPE, _fixture_source_counts(factory))
    return {
        "database_counts": report.database_counts,
        "invariant_violations": report.invariant_violations,
        "errors": report.errors,
        "coverage": report.coverage,
        "db_execution_status": report.db_execution_status,
    }


def _fixture_source_counts(factory: Callable[[], psycopg.Connection]) -> SourceCounts:
    """Read committed manifest counts; a quality proof must not reuse in-memory loader values."""
    with factory() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT attempted_counts FROM ingestion_runs WHERE status = 'succeeded' "
            "AND source_commit = %s ORDER BY finished_at DESC LIMIT 1",
            (SOURCE_COMMIT,),
        )
        row = cur.fetchone()
    assert row is not None
    assert isinstance(row[0], dict)
    return SourceCounts(**row[0])


def _build_and_audit(
    factory: Callable[[], psycopg.Connection],
) -> tuple[dict[str, Any], dict[str, Any]]:
    result = run_ingestion(factory, StatsBombSource(FIXTURE_ROOT, offline=True), FIXTURE_SCOPE)
    assert result.status == "succeeded"
    assert all(counts["inserted"] == counts["source"] for counts in result.entity_counts.values())
    quality = _quality_evidence(factory)
    assert quality["db_execution_status"] == "executed"
    assert all(count == 0 for count in quality["invariant_violations"].values())
    return _canonical_snapshot(factory), quality


def test_clean_rebuild_reproduces_canonical_fixture_snapshot(
    connection_factory: Callable[[], psycopg.Connection],
) -> None:
    """Two isolated empty-schema builds have equal source facts and quality evidence."""
    _prepare_empty_schema(connection_factory)
    first_snapshot, first_quality = _build_and_audit(connection_factory)

    _clean_schema(connection_factory)
    _prepare_empty_schema(connection_factory)
    second_snapshot, second_quality = _build_and_audit(connection_factory)

    assert first_snapshot == second_snapshot
    assert first_quality == second_quality
