"""Integration tests against a real PostgreSQL instance.

Skipped unless ``TOUCHLINE_DB_URL`` is set, so the ordinary test run stays fast and needs no
services. Start the database first:

    docker compose -f infra/docker-compose.yml up -d

These exist because every other test in this suite proves the *failure* path — that /ready degrades
when the database is gone. Without one test on the success path, a change that broke the connection
code entirely would still show a green suite.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from touchline.config import Settings
from touchline.main import app

DB_URL = os.environ.get("TOUCHLINE_DB_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        DB_URL is None,
        reason="TOUCHLINE_DB_URL not set; start infra/docker-compose.yml and copy .env.example",
    ),
]


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def test_settings_accept_the_real_dsn() -> None:
    """The DSN that actually works must also pass validation.

    A validator strict enough to reject the real connection string would be caught here rather
    than at deploy time.
    """
    settings = Settings()  # type: ignore[call-arg]
    assert settings.db_url_str


def test_database_accepts_a_connection_and_a_query() -> None:
    """The narrowest possible proof that the container, port mapping and credentials line up."""
    assert DB_URL is not None
    with psycopg.connect(DB_URL, connect_timeout=5) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone() == (1,)


def test_ready_reports_ready_against_a_live_database(client: TestClient) -> None:
    """The success path of the readiness probe.

    Every other ops test asserts /ready degrades. This is the one that proves it can ever be
    satisfied - without it, a probe hard-wired to "degraded" would pass the whole suite.
    """
    body = client.get("/ready").json()

    assert body["status"] == "ready"
    assert body["database"] == "reachable"
    assert body["detail"] is None


def test_health_still_reports_ok(client: TestClient) -> None:
    """Liveness is unaffected by database availability in either direction."""
    assert client.get("/health").json()["status"] == "ok"
