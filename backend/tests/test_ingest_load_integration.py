"""Loader tests that need a real PostgreSQL.

Skipped unless ``TOUCHLINE_DB_URL`` is set. These cover the one loader contract that cannot be
tested with the parser alone: WP0.3's loader is **not idempotent**, and it must say so rather than
duplicating rows.

Only the refusal path is tested automatically, because it raises before writing anything and is
therefore safe against a populated database. The success path is destructive by nature (it needs a
reset first) and is exercised by the CLI, whose reconciliation output is the check.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
import pytest

from touchline.ingest import load as loader
from touchline.ingest.records import Competition

DB_URL = os.environ.get("TOUCHLINE_DB_URL")

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
        yield connection


def _tables_exist(connection: psycopg.Connection) -> bool:
    with connection.cursor() as cur:
        cur.execute("SELECT to_regclass('public.shots')")
        row = cur.fetchone()
    return bool(row and row[0])


def test_schema_sql_ships_with_the_package() -> None:
    """The DDL is package data; a build that dropped it fails here, not at runtime."""
    ddl = loader.read_schema_sql()

    for table in ("competitions", "teams", "players", "matches", "shots"):
        assert f"CREATE TABLE {table}" in ddl


def test_loading_into_a_populated_database_is_refused(conn: psycopg.Connection) -> None:
    """The loader must refuse rather than duplicate.

    This is the contract that makes "not idempotent" safe to ship: the failure is an explicit
    message naming the fix, not a duplicate-key traceback and not silently doubled row counts.
    """
    if not _tables_exist(conn) or loader.count_rows(conn).shots == 0:
        pytest.skip("database is empty; run `uv run poe ingest --reset` first")

    with pytest.raises(loader.NotIdempotentError, match="not idempotent"):
        loader.load_all(
            conn,
            competitions=[Competition(43, 106, "FIFA World Cup", "2022", "International")],
            teams=[],
            players=[],
            matches=[],
            shots=[],
        )


def test_counts_read_back_from_the_database(conn: psycopg.Connection) -> None:
    """count_rows is what reconciliation compares against, so it must read the real tables."""
    if not _tables_exist(conn):
        pytest.skip("schema not created; run `uv run poe ingest --reset` first")

    counts = loader.count_rows(conn)

    assert counts.shots >= 0
    assert counts.matches >= 0
