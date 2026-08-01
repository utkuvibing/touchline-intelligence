"""Read-only shot endpoint tests against a real PostgreSQL.

Skipped unless ``TOUCHLINE_DB_URL`` is set. Uses the committed fixture in an isolated schema.

The contract under test is narrow and mostly negative: the endpoint returns recorded facts and
nothing else. No probability, no rating, no derived quality measure - because the moment one
appears in a payload, a client will render it, and M0 has no evaluated model to justify it.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from touchline.ingest import load as loader
from touchline.ingest.cli import collect
from touchline.ingest.source import StatsBombSource
from touchline.main import app
from touchline.shots import MAX_LIMIT, fetch_shots

DB_URL = os.environ.get("TOUCHLINE_DB_URL")
FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "statsbomb"
TEST_SCHEMA = "wp05_shots_test"

FIXTURE_SHOTS = 4

# Anything that would let a client draw a probability. None of these may appear in a payload while
# M0 has no evaluated model.
FORBIDDEN_FIELDS = {"xg", "x_g", "statsbomb_xg", "expected_goals", "probability", "prediction"}

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        DB_URL is None,
        reason="TOUCHLINE_DB_URL not set; start infra/docker-compose.yml and copy .env.example",
    ),
]


@pytest.fixture
def loaded_conn() -> Iterator[psycopg.Connection]:
    assert DB_URL is not None
    collected = collect(StatsBombSource(FIXTURES, offline=True), 43, 106)
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE')
            cur.execute(f'CREATE SCHEMA "{TEST_SCHEMA}"')
            cur.execute(f'SET search_path TO "{TEST_SCHEMA}"')
        loader.reset_schema(conn)
        loader.load_all(
            conn,
            competitions=collected.competitions,
            teams=collected.teams,
            players=collected.players,
            matches=collected.matches,
            shots=collected.shots,
            lineups=collected.lineups,
            memberships=collected.memberships,
            positions=collected.positions,
            cards=collected.cards,
            possessions=collected.possessions,
            events=collected.events,
            relations=collected.relations,
            freeze_frames=collected.freeze_frames,
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
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    assert DB_URL is not None
    monkeypatch.setenv("TOUCHLINE_DB_URL", f"{DB_URL}?options=-csearch_path%3D{TEST_SCHEMA}")
    with TestClient(app) as c:
        yield c


def test_returns_every_fixture_shot_with_its_recorded_facts(
    loaded_conn: psycopg.Connection, client: TestClient
) -> None:
    body = client.get("/shots").json()

    assert body["total"] == FIXTURE_SHOTS
    assert len(body["shots"]) == FIXTURE_SHOTS

    goal = next(s for s in body["shots"] if s["shot_id"].endswith("003"))
    assert goal["team"] == "Fixture United"
    assert goal["opponent"] == "Fixture Rovers"
    assert goal["player"] == "Bea Striker"
    assert (goal["location_x"], goal["location_y"]) == (112.0, 40.0)
    assert goal["outcome"] == "Goal"
    assert goal["body_part"] == "Right Foot"
    assert goal["match_date"] == "2022-11-20"


def test_payload_carries_no_probability_or_rating(
    loaded_conn: psycopg.Connection, client: TestClient
) -> None:
    """The negative contract, asserted rather than assumed.

    M0 has no evaluated model. A field that looks like a probability would be rendered by any
    client that received it, which is how an unevaluated number becomes a published claim.
    """
    body = client.get("/shots").json()

    for shot in body["shots"]:
        leaked = {key for key in shot if key.lower() in FORBIDDEN_FIELDS}
        assert not leaked, f"payload must carry no estimate, found {leaked}"


def test_unattributed_shot_is_returned_with_a_null_player(
    loaded_conn: psycopg.Connection, client: TestClient
) -> None:
    """An INNER JOIN would drop it and quietly change the shot count away from the source."""
    body = client.get("/shots").json()

    penalty = next(s for s in body["shots"] if s["shot_id"].endswith("006"))
    assert penalty["player"] is None
    assert penalty["shot_type"] == "Penalty"


def test_shot_without_a_location_is_returned_with_nulls(
    loaded_conn: psycopg.Connection, client: TestClient
) -> None:
    """Not dropped: a shot we cannot place is still a shot that happened."""
    body = client.get("/shots").json()

    unplaced = next(s for s in body["shots"] if s["shot_id"].endswith("005"))
    assert (unplaced["location_x"], unplaced["location_y"]) == (None, None)


def test_match_filter_restricts_the_page_and_the_total(
    loaded_conn: psycopg.Connection, client: TestClient
) -> None:
    """The total must reflect the filter, otherwise pagination lies about how much is left."""
    body = client.get("/shots", params={"match_id": 900002}).json()

    assert body["total"] == 0
    assert body["shots"] == []


def test_pagination_is_stable_and_reports_the_unpaged_total(
    loaded_conn: psycopg.Connection, client: TestClient
) -> None:
    first = client.get("/shots", params={"limit": 2, "offset": 0}).json()
    second = client.get("/shots", params={"limit": 2, "offset": 2}).json()

    assert first["total"] == second["total"] == FIXTURE_SHOTS
    assert len(first["shots"]) == len(second["shots"]) == 2
    assert {s["shot_id"] for s in first["shots"]}.isdisjoint(
        {s["shot_id"] for s in second["shots"]}
    )


def test_limit_above_the_maximum_is_rejected(
    loaded_conn: psycopg.Connection, client: TestClient
) -> None:
    """The bound is declared, so an over-large request is a validation error, not a surprise."""
    assert client.get("/shots", params={"limit": MAX_LIMIT + 1}).status_code == 422
    assert client.get("/shots", params={"limit": 0}).status_code == 422
    assert client.get("/shots", params={"offset": -1}).status_code == 422


def test_fetch_shots_makes_its_own_transaction_read_only(
    loaded_conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Read-only must be established by `fetch_shots`, not by the caller.

    An earlier version of this test called `fetch_shots` and then opened a *separate* transaction
    in which it ran `SET TRANSACTION READ ONLY` itself, and asserted a write failed there. That
    proved PostgreSQL honours the statement — which was never in doubt — and would have passed
    with the production statement deleted. A false positive.

    This asks the server, from inside whatever transaction `fetch_shots` established, whether that
    transaction is read-only. It observes real session state rather than inspecting SQL text, so
    removing the production `SET TRANSACTION READ ONLY` makes it fail.
    """
    observed: list[str] = []

    class ProbingCursor(psycopg.Cursor[Any]):
        """Records the transaction's read-only state after every statement it runs.

        Installed through psycopg's own `cursor_factory`, so `fetch_shots` is untouched and both
        of its cursors are covered.
        """

        def execute(self, *args: Any, **kwargs: Any) -> ProbingCursor:
            result = super().execute(*args, **kwargs)
            # A plain second cursor on the same connection is inside the same transaction, so
            # this reports the state fetch_shots actually established.
            with psycopg.Cursor(self.connection) as probe:
                probe.execute("SHOW transaction_read_only")
                row = probe.fetchone()
                observed.append(str(row[0]) if row else "unknown")
            return result

    monkeypatch.setattr(loaded_conn, "cursor_factory", ProbingCursor)

    fetch_shots(loaded_conn, limit=1)

    assert observed, "no statement was executed, so nothing was observed"
    assert observed[-1] == "on", (
        "the transaction fetch_shots ran its data query in was not read-only; "
        f"observed states in order: {observed}"
    )
