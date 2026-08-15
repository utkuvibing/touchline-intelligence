"""Database-backed WP3.1 historical prediction contracts over the synthetic fixture."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from support.db_safety import connect_local

from touchline.ingest import load as loader
from touchline.ingest.cli import collect
from touchline.ingest.source import StatsBombSource
from touchline.main import app
from touchline.model_shots import HistoricalFilters, fetch_historical_shots
from touchline.serving import HistoricalPredictionInput, ModelRuntime

DB_URL = os.environ.get("TOUCHLINE_DB_URL")
FIXTURES = Path(__file__).resolve().parents[2] / "data/fixtures/statsbomb"
TEST_SCHEMA = "wp31_model_shots_test"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(DB_URL is None, reason="TOUCHLINE_DB_URL not set"),
]


@pytest.fixture
def loaded_conn() -> Iterator[psycopg.Connection]:
    assert DB_URL is not None
    collected = collect(StatsBombSource(FIXTURES, offline=True), 43, 106)
    with connect_local(DB_URL) as connection:
        with connection.cursor() as cursor:
            cursor.execute(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE')
            cursor.execute(f'CREATE SCHEMA "{TEST_SCHEMA}"')
            cursor.execute(f'SET search_path TO "{TEST_SCHEMA}"')
        loader.reset_schema(connection)
        loader.load_all(
            connection,
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
        connection.commit()
        try:
            yield connection
        finally:
            connection.rollback()
            with connection.cursor() as cursor:
                cursor.execute(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE')
            connection.commit()


@pytest.fixture
def client(
    loaded_conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    assert DB_URL is not None
    del loaded_conn
    monkeypatch.setenv("TOUCHLINE_DB_URL", f"{DB_URL}?options=-csearch_path%3D{TEST_SCHEMA}")
    monkeypatch.setenv("TOUCHLINE_HISTORICAL_MODEL_SHOTS_ENABLED", "true")
    with TestClient(app) as instance:
        yield instance


def test_historical_endpoint_returns_only_eligible_rows_and_batches_once(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch_sizes: list[int] = []
    original = ModelRuntime.predict_historical

    def recording_predict(
        runtime: ModelRuntime, rows: list[HistoricalPredictionInput]
    ) -> list[float]:
        batch_sizes.append(len(rows))
        assert all(not hasattr(row, "outcome") for row in rows)
        return original(runtime, rows)

    monkeypatch.setattr(ModelRuntime, "predict_historical", recording_predict)
    response = client.get("/model/shots")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["shots"]) == 1
    assert body["split_role"] == "calibration_data_historical_predictions"
    assert body["shots"][0]["outcome"] == "Goal"
    assert body["shots"][0]["play_pattern"] == "None"
    assert 0.0 <= body["shots"][0]["calibrated_probability"] <= 1.0
    assert batch_sizes == [1]


def test_internal_tournament_rows_never_expand_the_public_historical_scope(
    loaded_conn: psycopg.Connection, client: TestClient
) -> None:
    with loaded_conn.cursor() as cursor:
        cursor.execute("INSERT INTO competitions VALUES (55, 'UEFA Euro', 'Europe')")
        cursor.execute("INSERT INTO seasons VALUES (282, '2024')")
        cursor.execute("INSERT INTO competition_seasons VALUES (55, 282)")
        cursor.execute("INSERT INTO teams VALUES (9901, 'Internal A'), (9902, 'Internal B')")
        cursor.execute("INSERT INTO players VALUES (9903, 'Internal Player')")
        cursor.execute(
            "INSERT INTO matches (match_id, competition_id, season_id, home_team_id, "
            "away_team_id) VALUES (990001, 55, 282, 9901, 9902)"
        )
        cursor.execute(
            "INSERT INTO match_teams VALUES (990001, 9901, 'home'), (990001, 9902, 'away')"
        )
        cursor.execute(
            "INSERT INTO events (event_id, match_id, event_index, period, minute, second, team_id, "
            "player_id, event_type_id, event_type_name, location_x, location_y, "
            "play_pattern_name) VALUES "
            "('dddddddd-0000-0000-0000-000000000001', 990001, 1, 1, 1, 1, 9901, 9903, "
            "16, 'Shot', 112, 40, 'Regular Play')"
        )
        cursor.execute(
            "INSERT INTO shots (event_id, outcome_name, shot_type_name, body_part_name, "
            "technique_name) VALUES "
            "('dddddddd-0000-0000-0000-000000000001', 'Goal', 'Open Play', "
            "'Right Foot', 'Normal')"
        )
    loaded_conn.commit()

    body = client.get("/model/shots").json()
    assert body["total"] == 1
    assert all(shot["match_id"] != 990001 for shot in body["shots"])


def test_penalty_exclusion_is_independent_of_other_required_fields(
    loaded_conn: psycopg.Connection, client: TestClient
) -> None:
    with loaded_conn.cursor() as cursor:
        cursor.execute(
            "UPDATE shots SET shot_type_name = 'Penalty' "
            "WHERE event_id = 'aaaaaaaa-0000-0000-0000-000000000003'"
        )
    loaded_conn.commit()

    body = client.get("/model/shots").json()
    assert body["total"] == 0
    assert body["shots"] == []


def test_filters_change_both_rows_and_total(client: TestClient) -> None:
    found = client.get("/model/shots", params={"team": "Fixture United", "limit": 1}).json()
    absent = client.get("/model/shots", params={"team": "Unknown Team"}).json()
    assert found["total"] == 1
    assert len(found["shots"]) == 1
    assert absent["total"] == 0
    assert absent["shots"] == []


def test_final_shot_id_tie_breaker_stabilizes_equal_recorded_order_fields(
    loaded_conn: psycopg.Connection, client: TestClient
) -> None:
    with loaded_conn.cursor() as cursor:
        # Source ingestion normally enforces unique (match_id, event_index). Drop that fixture-only
        # guard to exercise the endpoint's declared final UUID tie-breaker directly.
        cursor.execute("ALTER TABLE events DROP CONSTRAINT events_match_index_unique")
        cursor.execute(
            "INSERT INTO events (event_id, match_id, event_index, period, minute, second, team_id, "
            "player_id, event_type_id, event_type_name, location_x, location_y, "
            "play_pattern_name) VALUES "
            "('aaaaaaaa-0000-0000-0000-000000000009', 900001, 8, 1, 50, 0, 7001, 8002, "
            "16, 'Shot', 110, 40, 'Regular Play'), "
            "('aaaaaaaa-0000-0000-0000-000000000008', 900001, 8, 1, 50, 0, 7001, 8002, "
            "16, 'Shot', 110, 40, 'Regular Play')"
        )
        cursor.execute(
            "INSERT INTO shots (event_id, outcome_name, shot_type_name, body_part_name, "
            "technique_name) VALUES "
            "('aaaaaaaa-0000-0000-0000-000000000009', 'Off T', 'Open Play', "
            "'Right Foot', 'Normal'), "
            "('aaaaaaaa-0000-0000-0000-000000000008', 'Off T', 'Open Play', "
            "'Right Foot', 'Normal')"
        )
    loaded_conn.commit()

    body = client.get("/model/shots").json()
    tied = [shot["shot_id"] for shot in body["shots"] if shot["minute"] == 50]
    assert tied == [
        "aaaaaaaa-0000-0000-0000-000000000008",
        "aaaaaaaa-0000-0000-0000-000000000009",
    ]


def test_query_establishes_its_own_read_only_transaction(
    loaded_conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: list[str] = []

    class ProbingCursor(psycopg.Cursor[Any]):
        def execute(self, *args: Any, **kwargs: Any) -> ProbingCursor:
            result = super().execute(*args, **kwargs)
            with psycopg.Cursor(self.connection) as probe:
                probe.execute("SHOW transaction_read_only")
                row = probe.fetchone()
                observed.append(str(row[0]) if row else "unknown")
            return result

    monkeypatch.setattr(loaded_conn, "cursor_factory", ProbingCursor)
    fetch_historical_shots(loaded_conn, HistoricalFilters(limit=1))
    assert observed[-1] == "on"
