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
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE')
            cur.execute(f'CREATE SCHEMA "{TEST_SCHEMA}"')
            cur.execute(f'SET search_path TO "{TEST_SCHEMA}"')
        loader.reset_schema(conn)
        loader.load_all(
            conn,
            competitions=fixture_data.competitions,
            teams=fixture_data.teams,
            players=fixture_data.players,
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


def test_public_baseline_excludes_an_internal_cohort_tournament(
    loaded_conn: psycopg.Connection,
) -> None:
    """Loading Euro 2024 internally must not silently republish its outcomes."""
    with loaded_conn.cursor() as cur:
        cur.execute("INSERT INTO competitions VALUES (55, 'UEFA Euro', 'Europe')")
        cur.execute("INSERT INTO seasons VALUES (282, '2024')")
        cur.execute("INSERT INTO competition_seasons VALUES (55, 282)")
        cur.execute("INSERT INTO teams VALUES (9901, 'Internal A'), (9902, 'Internal B')")
        cur.execute(
            "INSERT INTO matches (match_id, competition_id, season_id, home_team_id, "
            "away_team_id) VALUES (990001, 55, 282, 9901, 9902)"
        )
        cur.execute("INSERT INTO match_teams VALUES (990001, 9901, 'home'), (990001, 9902, 'away')")
        cur.execute(
            "INSERT INTO events (event_id, match_id, event_index, period, team_id, "
            "event_type_id, event_type_name) VALUES "
            "('dddddddd-0000-0000-0000-000000000001', 990001, 1, 1, 9901, 16, 'Shot')"
        )
        cur.execute(
            "INSERT INTO shots (event_id, outcome_name, shot_type_name) VALUES "
            "('dddddddd-0000-0000-0000-000000000001', 'Goal', 'Open Play')"
        )

    rate = baseline.compute_base_rate(loaded_conn)

    assert (rate.goals, rate.shots) == (EXPECTED_GOALS, EXPECTED_SHOTS)


def test_empty_database_raises_rather_than_reporting_zero(empty_conn: psycopg.Connection) -> None:
    """ "Nothing ingested" and "nothing scored" are different facts.

    Returning 0.0 for an empty database would be a plausible-looking lie, and would also divide by
    zero on the way there.
    """
    with pytest.raises(baseline.NoDataError, match="no shots are loaded"):
        baseline.compute_base_rate(empty_conn)


@pytest.mark.parametrize(
    ("column", "reason"),
    [
        pytest.param(
            "shot_type",
            "NULL <> 'Penalty' is NULL, so the row would drop out silently - treated like a "
            "penalty, for an entirely different reason",
            id="missing-shot-type",
        ),
        pytest.param(
            "period",
            "same three-valued-logic trap as shot_type",
            id="missing-period",
        ),
        pytest.param(
            "outcome",
            "the dangerous one: the row stays in the denominator but fails the goal filter, so "
            "an unknown result is scored as a definite miss",
            id="missing-outcome",
        ),
    ],
)
def test_rows_with_missing_fields_leave_both_numerator_and_denominator(
    loaded_conn: psycopg.Connection, column: str, reason: str
) -> None:
    """A shot we do not know the result of must not be counted as one we do.

    Each case inserts one extra shot with a single field nulled out. The rate must be unchanged:
    the row belongs in neither the numerator nor the denominator.
    """
    values: dict[str, object] = {
        "event_id": "cccccccc-0000-0000-0000-000000000001",
        "period": 1,
        "shot_type_name": "Open Play",
        "outcome_name": "Off T",
    }
    db_column = {"shot_type": "shot_type_name", "period": "period", "outcome": "outcome_name"}[
        column
    ]
    values[db_column] = None

    with loaded_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO events (event_id, match_id, period, team_id, event_type_id, "
            "event_type_name)"
            " VALUES (%(event_id)s, 900001, %(period)s, 7001, 16, 'Shot')",
            values,
        )
        cur.execute(
            "INSERT INTO shots (event_id, shot_type_name, outcome_name)"
            " VALUES (%(event_id)s, %(shot_type_name)s, %(outcome_name)s)",
            values,
        )

    rate = baseline.compute_base_rate(loaded_conn)

    assert rate.shots == EXPECTED_SHOTS, reason
    assert rate.goals == EXPECTED_GOALS, reason


def test_cohort_predicate_is_documented_in_the_sql() -> None:
    """The executed SQL and the text published beside it must not drift apart.

    The API returns COHORT_DESCRIPTION to explain what the rate covers. If the predicate changed
    and the prose did not, the endpoint would describe a cohort it is not computing.
    """
    assert baseline.COHORT_PREDICATE in baseline.BASE_RATE_SQL
    assert "penalt" in baseline.COHORT_DESCRIPTION.lower()
    assert "shootout" in baseline.COHORT_DESCRIPTION.lower()
    assert "IS NOT NULL" in baseline.COHORT_PREDICATE
    assert "excluded from both" in baseline.COHORT_DESCRIPTION


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
    assert body["method"] == "descriptive-prevalence"
    assert body["shots"] == EXPECTED_SHOTS
    assert body["goals"] == EXPECTED_GOALS
    assert body["conversion_rate"] == pytest.approx(1 / 3)
    assert "not a model" in body["caveat"]
    assert "training split" in body["caveat"], "the caveat must say what the real baseline is"
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
