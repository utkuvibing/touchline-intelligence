"""Base-rate baseline tests against a real PostgreSQL.

Skipped unless ``TOUCHLINE_DB_URL`` is set. Uses the committed fixture in an isolated schema, so
the numbers are exact rather than "roughly right", and a developer's loaded World Cup data is
untouched.

The fixture holds four shots: three open-play (one Goal, one Off T, one Saved) and one Penalty
(Goal). The cohort excludes the penalty, so the expected rate is exactly 1/3 — and the penalty
being a goal is deliberate, because a filter that silently included it would raise the rate to 2/4
and still look plausible.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from touchline import baseline
from touchline.ingest import load as loader
from touchline.ingest.cli import CollectedScope, collect
from touchline.ingest.source import StatsBombSource
from touchline.main import app

DB_URL = os.environ.get("TOUCHLINE_DB_URL")
FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "statsbomb"
TEST_SCHEMA = "wp04_baseline_test"

EXPECTED_SHOTS = 3
EXPECTED_GOALS = 1

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        DB_URL is None,
        reason="TOUCHLINE_DB_URL not set; start infra/docker-compose.yml and copy .env.example",
    ),
]


@pytest.fixture
def fixture_data() -> CollectedScope:
    return collect(StatsBombSource(FIXTURES, offline=True), 43, 106)


@pytest.fixture
def loaded_conn(fixture_data: CollectedScope) -> Iterator[psycopg.Connection]:
    """A connection with the fixture loaded into a throwaway schema."""
    assert DB_URL is not None
    competitions, teams, players, matches, shots, _ = fixture_data
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE')
            cur.execute(f'CREATE SCHEMA "{TEST_SCHEMA}"')
            cur.execute(f'SET search_path TO "{TEST_SCHEMA}"')
        loader.reset_schema(conn)
        loader.load_all(
            conn,
            competitions=competitions,
            teams=teams,
            players=players,
            matches=matches,
            shots=shots,
        )
        conn.commit()
        try:
            yield conn
        finally:
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE')
            conn.commit()


@pytest.fixture
def empty_conn() -> Iterator[psycopg.Connection]:
    """A connection with the schema created but no rows loaded."""
    assert DB_URL is not None
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE')
            cur.execute(f'CREATE SCHEMA "{TEST_SCHEMA}"')
            cur.execute(f'SET search_path TO "{TEST_SCHEMA}"')
        loader.reset_schema(conn)
        conn.commit()
        try:
            yield conn
        finally:
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE')
            conn.commit()


def test_base_rate_excludes_penalties(loaded_conn: psycopg.Connection) -> None:
    """One of the fixture's two goals is a penalty and must not reach the numerator.

    Including it would give 2/4 = 0.5 instead of 1/3 — a wrong answer that still looks like a
    reasonable conversion rate, which is exactly why this is asserted on exact counts.
    """
    rate = baseline.compute_base_rate(loaded_conn)

    assert rate.shots == EXPECTED_SHOTS
    assert rate.goals == EXPECTED_GOALS
    assert rate.value == pytest.approx(1 / 3)


def test_empty_database_raises_rather_than_reporting_zero(empty_conn: psycopg.Connection) -> None:
    """ "Nothing ingested" and "nothing scored" are different facts.

    Returning 0.0 for an empty database would be a plausible-looking lie, and would also divide by
    zero on the way there.
    """
    with pytest.raises(baseline.NoDataError, match="no shots are loaded"):
        baseline.compute_base_rate(empty_conn)


def test_cohort_predicate_is_documented_in_the_sql() -> None:
    """The executed SQL and the text published beside it must not drift apart.

    The API returns COHORT_DESCRIPTION to explain what the rate covers. If the predicate changed
    and the prose did not, the endpoint would describe a cohort it is not computing.
    """
    assert baseline.COHORT_PREDICATE in baseline.BASE_RATE_SQL
    assert "penalt" in baseline.COHORT_DESCRIPTION.lower()
    assert "shootout" in baseline.COHORT_DESCRIPTION.lower()


def test_endpoint_serves_the_rate_with_its_denominator_and_caveat(
    loaded_conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The API must never publish a bare probability.

    The counts and the caveat are what stop the number reading as a model output.
    """
    assert DB_URL is not None
    monkeypatch.setenv("TOUCHLINE_DB_URL", f"{DB_URL}?options=-csearch_path%3D{TEST_SCHEMA}")

    with TestClient(app) as client:
        response = client.get("/baseline")

    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "constant-base-rate"
    assert body["shots"] == EXPECTED_SHOTS
    assert body["goals"] == EXPECTED_GOALS
    assert body["base_rate"] == pytest.approx(1 / 3)
    assert "not a model" in body["caveat"]
    assert "penalt" in body["cohort"].lower()


def test_endpoint_reports_503_when_nothing_is_loaded(
    empty_conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An instance with no data is unavailable, not broken and not empty-but-fine."""
    assert DB_URL is not None
    monkeypatch.setenv("TOUCHLINE_DB_URL", f"{DB_URL}?options=-csearch_path%3D{TEST_SCHEMA}")

    with TestClient(app) as client:
        response = client.get("/baseline")

    assert response.status_code == 503
    assert "ingest" in response.json()["detail"]
