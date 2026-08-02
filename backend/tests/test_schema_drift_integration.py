"""The production failure this build was repaired for: a database left behind by its own code.

The deployed API was serving a revision whose queries join `events`, against a managed database
still at the unversioned M0 five-table schema. `/baseline` and `/shots` raised `UndefinedTable`
and returned `503 {"detail":"UndefinedTable"}`, while `/health` said `ok` and `/ready` said
`ready`/`reachable` — because readiness ran `SELECT 1`, which succeeds against a database holding
no tables whatsoever.

Two contracts are protected here, and both failed in production:

1. **Readiness must notice.** An instance whose every data endpoint raises must not report ready.
2. **The 503 must say what is wrong.** `UndefinedTable` is the driver's symbol, not an
   explanation: it does not say which table, why it is absent, or what to do about it.

The "behind" schema is built by applying migration 0001 alone, which is exactly the unversioned M0
shape the live database was actually in — verified against it before this test was written, column
for column.

Skipped unless ``TOUCHLINE_DB_URL`` is set. Runs in a dedicated schema that is dropped afterwards.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from touchline import schema_state
from touchline.ingest.migrate import apply_migrations, read_migrations
from touchline.main import app

DB_URL = os.environ.get("TOUCHLINE_DB_URL")
TEST_SCHEMA = "schema_drift_test"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        DB_URL is None,
        reason="TOUCHLINE_DB_URL not set; start infra/docker-compose.yml and copy .env.example",
    ),
]


def _fresh_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE')
        cur.execute(f'CREATE SCHEMA "{TEST_SCHEMA}"')
        cur.execute(f'SET search_path TO "{TEST_SCHEMA}"')


def _drop_schema(conn: psycopg.Connection) -> None:
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE')
    conn.commit()


@pytest.fixture
def behind_conn() -> Iterator[psycopg.Connection]:
    """The unversioned M0 schema: the five original tables, and no `events`."""
    assert DB_URL is not None
    with psycopg.connect(DB_URL) as conn:
        _fresh_schema(conn)
        with conn.cursor() as cur:
            cur.execute(read_migrations()[0].sql)
        conn.commit()
        try:
            yield conn
        finally:
            _drop_schema(conn)


@pytest.fixture
def current_conn() -> Iterator[psycopg.Connection]:
    """The schema this build's queries were written against."""
    assert DB_URL is not None
    with psycopg.connect(DB_URL) as conn:
        _fresh_schema(conn)
        apply_migrations(conn)
        conn.commit()
        try:
            yield conn
        finally:
            _drop_schema(conn)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A client whose app connections land in the test schema, not in `public`."""
    monkeypatch.setenv("TOUCHLINE_DB_URL", f"{DB_URL}?options=-csearch_path%3D{TEST_SCHEMA}")
    monkeypatch.setenv("TOUCHLINE_ENVIRONMENT", "test")
    with TestClient(app) as c:
        yield c


def test_missing_required_tables_names_the_absent_relations(
    behind_conn: psycopg.Connection,
) -> None:
    """`events` is the relation WP1.2 introduced and the live database never received."""
    assert schema_state.missing_required_tables(behind_conn) == ("events",)


def test_a_current_schema_is_missing_nothing(current_conn: psycopg.Connection) -> None:
    """The mirror: a check that always reports drift would 'catch' the outage and nothing else."""
    assert schema_state.missing_required_tables(current_conn) == ()


def test_ready_reports_degraded_when_the_database_is_reachable_but_behind(
    behind_conn: psycopg.Connection, client: TestClient
) -> None:
    """The regression test for the outage itself.

    Before this change the assertion below read `ready`/`reachable` against precisely this
    database state, which is why a completely unservable deployment looked healthy from outside.
    """
    body = client.get("/ready").json()

    assert body["status"] == "degraded"
    assert body["database"] == "reachable", "PostgreSQL genuinely does answer; that was the trap"
    assert body["database_schema"] == "behind"


def test_ready_reports_ready_against_a_current_schema(
    current_conn: psycopg.Connection, client: TestClient
) -> None:
    """A readiness probe that never says ready is as useless as one that always does."""
    body = client.get("/ready").json()

    assert body["status"] == "ready"
    assert body["database"] == "reachable"
    assert body["database_schema"] == "current"
    assert body["detail"] is None


@pytest.mark.parametrize("path", ["/baseline", "/shots"])
def test_data_endpoints_explain_drift_instead_of_naming_the_driver_symbol(
    behind_conn: psycopg.Connection, client: TestClient, path: str
) -> None:
    """503 is right; `UndefinedTable` as the whole explanation is not.

    The status is unchanged deliberately — this instance really cannot serve the request. What
    changes is that the body now names the cause and the operator action.
    """
    response = client.get(path)

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail == schema_state.SCHEMA_NOT_MIGRATED_DETAIL
    assert detail != "UndefinedTable"
    assert "migrations" in detail


def test_the_drift_detail_carries_no_connection_fragments(
    behind_conn: psycopg.Connection, client: TestClient
) -> None:
    """The endpoint is unauthenticated, so its error body must not echo the DSN.

    Asserted as a positive property — the detail is a fixed module constant, so it cannot contain
    anything derived from the connection — plus a direct check against the live DSN's own parts,
    which is what a driver message would have leaked.
    """
    assert DB_URL is not None
    detail = client.get("/baseline").json()["detail"]

    assert detail == schema_state.SCHEMA_NOT_MIGRATED_DETAIL
    for fragment in ("://", "@", TEST_SCHEMA):
        assert fragment not in detail
