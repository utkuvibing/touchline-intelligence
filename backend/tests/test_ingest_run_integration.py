"""WP1.3 ingestion lifecycle tests at its public PostgreSQL seam."""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from typing import Any

import psycopg
import pytest
from support.db_safety import connect_local

from touchline.ingest import load as loader
from touchline.ingest import run as ingestion_run
from touchline.ingest.cli import collect
from touchline.ingest.run import (
    CORE_COHORT,
    ConcurrentIngestionError,
    SourceCommitConflictError,
    SourceConflictError,
    collect_cohort,
    run_ingestion,
)
from touchline.ingest.source import StatsBombSource

DB_URL = os.environ.get("TOUCHLINE_DB_URL")
FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "statsbomb"
TEST_SCHEMA = "wp13_ingestion_test"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        DB_URL is None,
        reason="TOUCHLINE_DB_URL not set; start infra/docker-compose.yml and copy .env.example",
    ),
]


@pytest.fixture
def connection_factory() -> Iterator[Callable[[], psycopg.Connection]]:
    assert DB_URL is not None
    with connect_local(DB_URL) as setup:
        with setup.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE')
            cur.execute(f'CREATE SCHEMA "{TEST_SCHEMA}"')
            cur.execute(f'SET search_path TO "{TEST_SCHEMA}"')
        loader.reset_schema(setup)
        setup.commit()

    def make_connection() -> psycopg.Connection:
        connection = connect_local(DB_URL)
        with connection.cursor() as cur:
            cur.execute(f'SET search_path TO "{TEST_SCHEMA}"')
        connection.commit()
        return connection

    try:
        yield make_connection
    finally:
        with connect_local(DB_URL) as cleanup:
            with cleanup.cursor() as cur:
                cur.execute(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE')
            cleanup.commit()


@pytest.fixture
def fixture_source() -> StatsBombSource:
    return StatsBombSource(FIXTURES, offline=True)


def test_collect_cohort_uses_the_explicit_scope_order(fixture_source: StatsBombSource) -> None:
    """The public collection seam accepts a fixed, inspectable cohort definition."""
    collected = collect_cohort(fixture_source, ((43, 106),))
    legacy = collect(StatsBombSource(FIXTURES, offline=True), 43, 106)

    assert CORE_COHORT == ((43, 3), (55, 43), (43, 106), (55, 282))
    assert collected.matches == legacy.matches
    assert collected.events == legacy.events
    assert collected.source_counts == legacy.source_counts


def test_first_load_and_identical_rerun_are_auditable_noops(
    connection_factory: Callable[[], psycopg.Connection], fixture_source: StatsBombSource
) -> None:
    """Every invocation has a manifest; the second identical source writes no facts."""
    first = run_ingestion(connection_factory, fixture_source, ((43, 106),))
    with connection_factory() as conn, conn.cursor() as cur:
        cur.execute("SELECT event_id::text, xmin::text FROM events ORDER BY event_id")
        event_versions_before = cur.fetchall()

    second = run_ingestion(
        connection_factory, StatsBombSource(FIXTURES, offline=True), ((43, 106),)
    )

    assert first.entity_counts["events"]["inserted"] == 9
    assert first.entity_counts["events"]["updated"] == 0
    assert second.entity_counts["events"]["inserted"] == 0
    assert second.entity_counts["events"]["updated"] == 0
    assert second.entity_counts["events"]["unchanged"] == 9

    with connection_factory() as conn, conn.cursor() as cur:
        cur.execute("SELECT status, entity_counts FROM ingestion_runs ORDER BY started_at")
        rows = cur.fetchall()
        cur.execute("SELECT count(*) FROM events")
        event_count = cur.fetchone()
        cur.execute("SELECT event_id::text, xmin::text FROM events ORDER BY event_id")
        event_versions_after = cur.fetchall()
    assert [row[0] for row in rows] == ["succeeded", "succeeded"]
    assert rows[1][1]["events"]["inserted"] == 0
    assert event_count == (9,)
    assert event_versions_after == event_versions_before


def test_changed_match_fact_rejects_the_whole_second_data_transaction(
    connection_factory: Callable[[], psycopg.Connection], fixture_source: StatsBombSource
) -> None:
    """A changed source key is evidence conflict, not permission to overwrite history."""
    run_ingestion(connection_factory, fixture_source, ((43, 106),))

    class ChangedMatchSource(StatsBombSource):
        def matches(self, competition_id: int, season_id: int) -> list[dict[str, object]]:
            rows = super().matches(competition_id, season_id)
            changed = [dict(row) for row in rows]
            changed[0]["home_score"] = 99
            return changed

    with pytest.raises(SourceConflictError, match="matches"):
        run_ingestion(connection_factory, ChangedMatchSource(FIXTURES, offline=True), ((43, 106),))

    with connection_factory() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM matches")
        matches = cur.fetchone()
        cur.execute(
            "SELECT status, error_type, entity_counts FROM ingestion_runs "
            "ORDER BY started_at DESC LIMIT 1"
        )
        failed = cur.fetchone()
    assert matches == (2,)
    assert failed is not None
    assert failed[0:2] == ("failed", "source_conflict")
    assert failed[2]["matches"] == {
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "rejected": 1,
        "source": 2,
        "final_scoped": 0,
    }


def test_changed_shared_dimension_label_is_rejected(
    connection_factory: Callable[[], psycopg.Connection], fixture_source: StatsBombSource
) -> None:
    """Labels are not keys, but a changed canonical source label is still a changed fact."""
    run_ingestion(connection_factory, fixture_source, ((43, 106),))

    class ChangedCompetitionSource(StatsBombSource):
        def competitions(self) -> list[dict[str, object]]:
            rows = super().competitions()
            changed = [dict(row) for row in rows]
            changed[0]["competition_name"] = "Changed Competition Label"
            return changed

    with pytest.raises(SourceConflictError, match="competitions"):
        run_ingestion(
            connection_factory,
            ChangedCompetitionSource(FIXTURES, offline=True),
            ((43, 106),),
        )


def test_populated_database_cannot_mix_successful_source_commits(
    connection_factory: Callable[[], psycopg.Connection], fixture_source: StatsBombSource
) -> None:
    """A successful manifest binds later source-derived merges to that source revision."""
    with connection_factory() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_runs (
                run_id, owner_token, source_commit, status, scopes, finished_at,
                owner_host, owner_pid, current_phase
            ) VALUES (
                '00000000-0000-0000-0000-000000000005',
                '00000000-0000-0000-0000-000000000006',
                'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                'succeeded', '[]'::jsonb, CURRENT_TIMESTAMP, 'prior-host', 1, 'completed'
            )
            """
        )
        conn.commit()

    with pytest.raises(SourceCommitConflictError):
        run_ingestion(connection_factory, fixture_source, ((43, 106),))

    with connection_factory() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM matches")
        assert cur.fetchone() == (0,)
        cur.execute("SELECT status, error_type FROM ingestion_runs ORDER BY started_at, run_id")
        assert cur.fetchall() == [
            ("succeeded", None),
            ("failed", "source_commit_conflict"),
        ]


EventMutator = Callable[[list[dict[str, Any]]], None]
LineupMutator = Callable[[list[dict[str, Any]]], None]


@pytest.mark.parametrize(
    ("expected_table", "event_mutator", "lineup_mutator"),
    [
        pytest.param(
            "events",
            lambda rows: rows[1]["pass"]["height"].update({"name": "Changed Height"}),
            None,
            id="generic-event-jsonb",
        ),
        pytest.param(
            "lineup_memberships",
            None,
            lambda rows: rows[0]["lineup"][0].update({"jersey_number": 99}),
            id="lineup-membership",
        ),
        pytest.param(
            "lineup_positions",
            None,
            lambda rows: rows[0]["lineup"][0]["positions"].insert(
                0,
                {
                    **rows[0]["lineup"][0]["positions"][0],
                    "position": "Changed First Position",
                },
            ),
            id="lineup-child-ordering",
        ),
        pytest.param(
            "shots",
            lambda rows: rows[2]["shot"]["outcome"].update({"name": "Saved"}),
            None,
            id="shot-typed-detail",
        ),
        pytest.param(
            "event_relations",
            lambda rows: rows[1].update(
                {"related_events": ["aaaaaaaa-0000-0000-0000-000000000004"]}
            ),
            None,
            id="directed-event-relation",
        ),
        pytest.param(
            "shot_freeze_frame_players",
            lambda rows: rows[2]["shot"]["freeze_frame"][0].update({"location": [107.0, 42.0]}),
            None,
            id="freeze-frame-actor",
        ),
    ],
)
def test_changed_child_or_json_fact_is_rejected(
    connection_factory: Callable[[], psycopg.Connection],
    fixture_source: StatsBombSource,
    expected_table: str,
    event_mutator: EventMutator | None,
    lineup_mutator: LineupMutator | None,
) -> None:
    """Every source-owned child/detail field participates in structural conflict detection."""
    run_ingestion(connection_factory, fixture_source, ((43, 106),))

    class ChangedFactSource(StatsBombSource):
        def events(self, match_id: int) -> list[dict[str, Any]]:
            rows = deepcopy(super().events(match_id))
            if event_mutator is not None and match_id == 900001:
                event_mutator(rows)
            return rows

        def lineups(self, match_id: int) -> list[dict[str, Any]]:
            rows = deepcopy(super().lineups(match_id))
            if lineup_mutator is not None and match_id == 900001:
                lineup_mutator(rows)
            return rows

    with pytest.raises(SourceConflictError, match=expected_table):
        run_ingestion(connection_factory, ChangedFactSource(FIXTURES, offline=True), ((43, 106),))

    with connection_factory() as conn, conn.cursor() as cur:
        cur.execute("SELECT entity_counts FROM ingestion_runs ORDER BY started_at DESC LIMIT 1")
        failed = cur.fetchone()
    assert failed is not None
    assert failed[0][expected_table]["rejected"] == 1


def test_source_child_deletion_is_rejected_by_exact_scoped_reconciliation(
    connection_factory: Callable[[], psycopg.Connection], fixture_source: StatsBombSource
) -> None:
    """An existing selected-scope child cannot disappear silently from a later source view."""
    run_ingestion(connection_factory, fixture_source, ((43, 106),))

    class MissingPositionSource(StatsBombSource):
        def lineups(self, match_id: int) -> list[dict[str, Any]]:
            rows = deepcopy(super().lineups(match_id))
            if match_id == 900001:
                rows[0]["lineup"][0]["positions"].pop()
            return rows

    with pytest.raises(SourceConflictError, match="lineup_positions"):
        run_ingestion(
            connection_factory,
            MissingPositionSource(FIXTURES, offline=True),
            ((43, 106),),
        )


def test_bad_event_after_staging_rolls_back_every_fact_and_records_failure(
    connection_factory: Callable[[], psycopg.Connection], fixture_source: StatsBombSource
) -> None:
    """A late FK error may not retain the earlier staged/merged entity families."""

    class BadEventSource(StatsBombSource):
        def events(self, match_id: int) -> list[dict[str, object]]:
            rows = super().events(match_id)
            changed = [dict(row) for row in rows]
            changed[0]["team"] = {"id": 999999, "name": "Not A Match Team"}
            return changed

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        run_ingestion(connection_factory, BadEventSource(FIXTURES, offline=True), ((43, 106),))

    with connection_factory() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM matches")
        matches = cur.fetchone()
        cur.execute("SELECT status, error_type, entity_counts FROM ingestion_runs")
        failed = cur.fetchone()
    assert matches == (0,)
    assert failed is not None
    assert failed[0] == "failed"
    assert str(failed[1]).startswith("database_error")
    assert failed[2] == {}, "failed manifests must not claim rolled-back writes"


def test_locked_active_run_is_not_reclassified_as_interrupted(
    connection_factory: Callable[[], psycopg.Connection], fixture_source: StatsBombSource
) -> None:
    """The session lock, not a time guess, distinguishes a live owner from an abandoned run."""
    with connection_factory() as held:
        with held.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestion_runs (
                    run_id, owner_token, source_commit, status, scopes, owner_host, owner_pid,
                    current_phase
                ) VALUES (
                    '00000000-0000-0000-0000-000000000003',
                    '00000000-0000-0000-0000-000000000004',
                    'b0bc9f22dd77c206ddedc1d742893b3bbe64baec',
                    'running', '[]'::jsonb, 'active-host', 1, 'collecting'
                )
                """
            )
            cur.execute(
                "SELECT pg_advisory_lock(hashtext(current_database()), hashtext(current_schema()))"
            )
        held.commit()

        with pytest.raises(ConcurrentIngestionError):
            run_ingestion(connection_factory, fixture_source, ((43, 106),))

        with connection_factory() as observer, observer.cursor() as cur:
            cur.execute("SELECT status, error_type FROM ingestion_runs ORDER BY started_at, run_id")
            rows = cur.fetchall()
    assert rows == [("running", None), ("failed", "concurrent_ingestion")]


def test_recovery_waits_for_a_contender_to_finish_its_manifest(
    connection_factory: Callable[[], psycopg.Connection],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new main owner cannot recover a contender between its two manifest commits."""
    contender_recorded = threading.Event()
    allow_contender_failure = threading.Event()
    first_record_lock = threading.Lock()
    first_record_pending = True
    original_record_running = ingestion_run._record_running

    def pause_first_record(
        conn: psycopg.Connection,
        run_id: uuid.UUID,
        owner_token: uuid.UUID,
        scopes: Sequence[tuple[int, int]],
    ) -> None:
        nonlocal first_record_pending
        original_record_running(conn, run_id, owner_token, scopes)
        with first_record_lock:
            pause = first_record_pending
            first_record_pending = False
        if pause:
            contender_recorded.set()
            assert allow_contender_failure.wait(timeout=10)

    monkeypatch.setattr(ingestion_run, "_record_running", pause_first_record)

    successor_pid: list[int] = []
    successor_connected = threading.Event()

    def successor_factory() -> psycopg.Connection:
        conn = connection_factory()
        if not successor_pid:
            successor_pid.append(conn.info.backend_pid)
            successor_connected.set()
        return conn

    with connection_factory() as held, held.cursor() as cur:
        cur.execute(
            "SELECT pg_advisory_lock(hashtext(current_database()), hashtext(current_schema()))"
        )
        held.commit()

        with ThreadPoolExecutor(max_workers=2) as executor:
            contender = executor.submit(
                run_ingestion,
                connection_factory,
                StatsBombSource(FIXTURES, offline=True),
                ((43, 106),),
            )
            assert contender_recorded.wait(timeout=10)

            cur.execute(
                "SELECT pg_advisory_unlock("
                "hashtext(current_database()), hashtext(current_schema()))"
            )
            held.commit()
            successor = executor.submit(
                run_ingestion,
                successor_factory,
                StatsBombSource(FIXTURES, offline=True),
                ((43, 106),),
            )
            assert successor_connected.wait(timeout=10)

            deadline = time.monotonic() + 10
            recovery_waited = False
            while time.monotonic() < deadline:
                with connection_factory() as observer, observer.cursor() as observer_cur:
                    observer_cur.execute(
                        "SELECT EXISTS (SELECT FROM pg_locks "
                        "WHERE pid = %s AND locktype = 'advisory' AND NOT granted)",
                        (successor_pid[0],),
                    )
                    row = observer_cur.fetchone()
                if row is not None and row[0]:
                    recovery_waited = True
                    break
                if successor.done():
                    break
                time.sleep(0.01)

            allow_contender_failure.set()
            with pytest.raises(ConcurrentIngestionError):
                contender.result(timeout=10)
            result = successor.result(timeout=10)

    assert recovery_waited, "recovery must wait for every live manifest lifecycle holder"
    assert result.status == "succeeded"
    with connection_factory() as conn, conn.cursor() as cur:
        cur.execute("SELECT status, error_type FROM ingestion_runs ORDER BY started_at, run_id")
        rows = cur.fetchall()
    assert rows == [("failed", "concurrent_ingestion"), ("succeeded", None)]


def test_next_lock_owner_recovers_abandoned_running_manifest(
    connection_factory: Callable[[], psycopg.Connection], fixture_source: StatsBombSource
) -> None:
    """A prior durable running row becomes explicitly interrupted only under exclusive ownership."""
    with connection_factory() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_runs (
                run_id, owner_token, source_commit, status, scopes, owner_host, owner_pid,
                current_phase
            ) VALUES (
                '00000000-0000-0000-0000-000000000001',
                '00000000-0000-0000-0000-000000000002',
                'b0bc9f22dd77c206ddedc1d742893b3bbe64baec',
                'running', '[]'::jsonb, 'abandoned-host', 1, 'staging'
            )
            """
        )
        conn.commit()

    result = run_ingestion(connection_factory, fixture_source, ((43, 106),))

    with connection_factory() as conn, conn.cursor() as cur:
        cur.execute("SELECT status, error_type FROM ingestion_runs ORDER BY started_at, run_id")
        rows = cur.fetchall()
    assert result.status == "succeeded"
    assert rows[0] == ("interrupted", "interrupted_or_abandoned")
    assert rows[1] == ("succeeded", None)

    retry = run_ingestion(connection_factory, StatsBombSource(FIXTURES, offline=True), ((43, 106),))
    assert retry.entity_counts["events"]["inserted"] == 0
    assert retry.entity_counts["events"]["updated"] == 0
