"""Liveness and readiness contract tests.

The distinction being protected: /health must not depend on the database, and /ready must. Getting
this backwards causes a platform to restart healthy instances during a database blip, or to route
traffic to instances that cannot answer a query.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

import psycopg
import pytest
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


def test_ready_does_open_a_database_connection(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mirror of the test above: /ready is worthless if it never queries."""
    calls: list[str] = []

    original_connect = psycopg.connect

    def _recording_connect(*args: object, **kwargs: object) -> object:
        calls.append("connect")
        return original_connect(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(psycopg, "connect", _recording_connect)

    client.get("/ready")

    assert calls == ["connect"]


def test_ready_reports_degraded_when_the_database_is_unreachable(client: TestClient) -> None:
    """If this ever returns "ready" against a dead database, the check is not checking anything."""
    response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unreachable"


def test_ready_reports_only_an_exception_class_name(client: TestClient) -> None:
    """Driver errors can echo host, port, user and database name, and /ready is unauthenticated.

    This asserts a positive shape rather than a blocklist of forbidden substrings. A blocklist
    passes for the wrong reason whenever the particular error happens not to contain the words
    being searched for - which is exactly what happened when this check was written the other way
    round: swapping `type(exc).__name__` for `str(exc)` did not fail it.

    An exception class name is a bare Python identifier. Any message, DSN fragment or host will
    contain spaces, punctuation or digits-at-the-start and fail this.
    """
    detail = client.get("/ready").json()["detail"]

    assert detail is not None, "an unreachable database must report some detail"
    assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", detail), (
        f"detail must be an exception class name only, got: {detail!r}"
    )
