"""Liveness and readiness contract tests.

The distinction being protected: /health must not depend on the database, and /ready must. Getting
this backwards causes a platform to restart healthy instances during a database blip, or to route
traffic to instances that cannot answer a query.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import cast

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from touchline.main import app

UNREACHABLE_DSN = "postgresql://nobody:nothing@127.0.0.1:1/nonexistent"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point the app at a port nothing listens on, so readiness genuinely fails."""
    monkeypatch.setenv("TOUCHLINE_DB_URL", UNREACHABLE_DSN)
    monkeypatch.setenv("TOUCHLINE_ENVIRONMENT", "test")
    yield


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def test_health_reports_ok_while_the_database_is_unreachable(client: TestClient) -> None:
    """The database is unreachable in this test, and /health must still report ok."""
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["environment"] == "test"


def test_health_opens_no_database_connection(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """/health must not touch the database at all.

    Asserting on the response body is not enough: if /health started calling the database, it would
    still return "ok" (the check swallows failures) and only get slower. A behavioural assertion
    would pass while the contract was broken. So this spies on the driver instead and asserts the
    connection is never opened.

    This test exists because the weaker version of it did not fail when the break was introduced
    deliberately.
    """
    calls: list[str] = []

    def _recording_connect(*args: object, **kwargs: object) -> object:
        calls.append("connect")
        raise AssertionError("/health must not open a database connection")

    monkeypatch.setattr(psycopg, "connect", _recording_connect)

    response = client.get("/health")

    assert response.status_code == 200
    assert calls == []


def test_ready_uses_the_application_lifetime_pool(client: TestClient) -> None:
    """Readiness must share the bounded runtime pool, rather than opening a direct connection."""
    assert cast(FastAPI, client.app).state.db_pool.max_size == 4
    assert client.get("/ready").status_code == 503


def test_ready_reports_degraded_when_the_database_is_unreachable(client: TestClient) -> None:
    """If this ever returns "ready" against a dead database, the check is not checking anything."""
    response = client.get("/ready")

    # WP3.1 intentionally changed degraded readiness from a nominal HTTP 200 to the status code
    # deployment routers can act on. Deterministic model corruption never reaches this endpoint;
    # this is a genuine runtime dependency failure.
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unreachable"
    assert body["model_runtime"] == "ready"
    assert body["model_version"] == "exp-20260810-wp2_8-release"


def test_ready_does_not_claim_to_know_the_schema_of_a_database_it_cannot_reach(
    client: TestClient,
) -> None:
    """Unreachable and behind are different diagnoses pointing at different fixes.

    Reporting the schema as "current" here would be a guess, and reporting it as "behind" would
    send an operator to run migrations against a database that is not answering at all.
    """
    assert client.get("/ready").json()["database_schema"] == "unknown"


def test_ready_uses_a_fixed_public_database_failure_code(client: TestClient) -> None:
    """Driver errors can echo host, port, user and database name, so readiness stays opaque."""
    detail = client.get("/ready").json()["detail"]

    assert detail == "database_unavailable"
