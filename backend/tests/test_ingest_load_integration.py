"""Loader tests that need a real PostgreSQL.

Skipped unless ``TOUCHLINE_DB_URL`` is set. CI provides a service container; locally, start
``infra/docker-compose.yml``.

These use the **committed fixture**, never the real StatsBomb download, so they are deterministic
and cost nothing in CI.

Isolation: every test runs inside a dedicated PostgreSQL schema that is created and dropped around
it. The provisional DDL uses unqualified table names, so a `search_path` is enough to keep a
destructive reset away from a developer's loaded World Cup data.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import psycopg
import pytest
from support.db_safety import connect_local

from touchline.ingest import load as loader
from touchline.ingest.cli import (
    CollectedScope,
    ReconciliationError,
    SourceCounts,
    collect,
    reconcile,
)
from touchline.ingest.records import Competition
from touchline.ingest.source import StatsBombSource
from touchline.quality import inspect
from touchline.quality_cli import _latest_matching_manifest

DB_URL = os.environ.get("TOUCHLINE_DB_URL")
FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "statsbomb"
TEST_SCHEMA = "wp03_fixture_test"

# Exactly what the committed fixture contains. Hard-coded rather than derived, so a change to the
# fixture or the parser has to be acknowledged here.
EXPECTED = loader.LoadCounts(
    competitions=1,
    seasons=1,
    competition_seasons=1,
    teams=3,
    players=4,
    matches=2,
    match_teams=4,
    lineups=4,
    lineup_memberships=5,
    lineup_positions=1,
    lineup_cards=1,
    possessions=1,
    events=9,
    event_relations=2,
    shots=4,
    shot_freeze_frame_players=1,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        DB_URL is None,
        reason="TOUCHLINE_DB_URL not set; start infra/docker-compose.yml and copy .env.example",
    ),
]


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    """A connection whose tables live in a throwaway schema, dropped afterwards."""
    assert DB_URL is not None
    with connect_local(DB_URL) as connection:
        with connection.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE')
            cur.execute(f'CREATE SCHEMA "{TEST_SCHEMA}"')
            cur.execute(f'SET search_path TO "{TEST_SCHEMA}"')
        connection.commit()
        try:
            yield connection
        finally:
            connection.rollback()
            with connection.cursor() as cur:
                cur.execute(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE')
            connection.commit()


@pytest.fixture
def fixture_data() -> CollectedScope:
    """Parse the committed fixture through the real collect() path."""
    source = StatsBombSource(FIXTURES, offline=True)
    return collect(source, 43, 106)


def _counts_in_new_transaction() -> loader.LoadCounts:
    """Read counts over a *separate* connection, so only committed data is visible."""
    assert DB_URL is not None
    with connect_local(DB_URL) as other, other.cursor() as cur:
        cur.execute(f'SET search_path TO "{TEST_SCHEMA}"')
        counts = {}
        for table in loader.LoadCounts.__dataclass_fields__:
            # Table names come from the fixed tuple above, not from input.
            cur.execute(f"SELECT count(*) FROM {table}")
            row = cur.fetchone()
            counts[table] = int(row[0]) if row else 0
    return loader.LoadCounts(**counts)


def _load_fixture(conn: psycopg.Connection, scope: CollectedScope) -> loader.LoadCounts:
    return loader.load_all(
        conn,
        competitions=scope.competitions,
        teams=scope.teams,
        players=scope.players,
        matches=scope.matches,
        shots=scope.shots,
        lineups=scope.lineups,
        memberships=scope.memberships,
        positions=scope.positions,
        cards=scope.cards,
        possessions=scope.possessions,
        events=scope.events,
        relations=scope.relations,
        freeze_frames=scope.freeze_frames,
    )


def test_reset_schema_rebuilds_through_ordered_migrations(conn: psycopg.Connection) -> None:
    """The destructive local rebuild must use the same versioned schema path as an upgrade."""
    loader.reset_schema(conn)

    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations ORDER BY version")
        versions = [row[0] for row in cur.fetchall()]

    assert versions == [
        "0001_initial",
        "0002_relational_constraints",
        "0003_normalize_competition_seasons",
        "0004_event_and_lineup_core",
        "0005_event_and_lineup_constraints",
        "0006_ingestion_runs",
        "0007_measured_event_x_boundary",
    ]


def test_successful_load_writes_exactly_the_fixture(
    conn: psycopg.Connection, fixture_data: CollectedScope
) -> None:
    """The happy path: reset, load, reconcile, commit - with exact counts."""
    loader.reset_schema(conn)
    _load_fixture(conn, fixture_data)
    db_counts = loader.count_rows(conn)

    assert db_counts == EXPECTED
    assert reconcile(fixture_data.source_counts, db_counts) is True

    conn.commit()
    assert _counts_in_new_transaction() == EXPECTED


def test_independent_quality_report_reconciles_the_fixture_after_commit(
    conn: psycopg.Connection, fixture_data: CollectedScope
) -> None:
    """WP1.4 audits a completed load in read-only mode, outside the ingestion transaction."""
    loader.reset_schema(conn)
    _load_fixture(conn, fixture_data)
    conn.commit()

    report = inspect(conn, ((43, 106),), fixture_data.source_counts)

    assert report.errors == ("shots missing future-cohort eligibility/feature fields: 3",)
    assert report.database_counts == {
        name: getattr(EXPECTED, name) for name in report.database_counts
    }
    # This literal is independent of the implementation's values/denominators loop. It binds every
    # published metric, including integer basis-point rounding, to the committed fixture.
    assert report.coverage == {
        "shots_without_location_count": 1,
        "shots_without_location_denominator": 4,
        "shots_without_location_basis_points": 2_500,
        "shots_without_attributed_player_count": 1,
        "shots_without_attributed_player_denominator": 4,
        "shots_without_attributed_player_basis_points": 2_500,
        "shots_missing_any_future_cohort_field_count": 3,
        "shots_missing_any_future_cohort_field_denominator": 4,
        "shots_missing_any_future_cohort_field_basis_points": 7_500,
        "lineup_memberships_without_position_interval_count": 4,
        "lineup_memberships_without_position_interval_denominator": 5,
        "lineup_memberships_without_position_interval_basis_points": 8_000,
        "events_at_measured_x_120_1_count": 0,
        "events_at_measured_x_120_1_denominator": 9,
        "events_at_measured_x_120_1_basis_points": 0,
        "events_without_player_count": 4,
        "events_without_player_denominator": 9,
        "events_without_player_basis_points": 4_444,
        "events_without_location_count": 4,
        "events_without_location_denominator": 9,
        "events_without_location_basis_points": 4_444,
        "events_without_position_count": 7,
        "events_without_position_denominator": 9,
        "events_without_position_basis_points": 7_777,
        "events_without_duration_count": 8,
        "events_without_duration_denominator": 9,
        "events_without_duration_basis_points": 8_888,
        "event_actors_without_same_match_team_lineup_membership_count": 0,
        "event_actors_without_same_match_team_lineup_membership_denominator": 5,
        "event_actors_without_same_match_team_lineup_membership_basis_points": 0,
    }


def test_quality_report_fails_an_exact_source_count_mismatch(
    conn: psycopg.Connection, fixture_data: CollectedScope
) -> None:
    """A report cannot silently turn a scoped source/table disagreement into a warning."""
    loader.reset_schema(conn)
    _load_fixture(conn, fixture_data)
    conn.commit()

    report = inspect(conn, ((43, 106),), replace(fixture_data.source_counts, events=10))

    assert report.errors == (
        "source/database count mismatch for events: 10 != 9",
        "shots missing future-cohort eligibility/feature fields: 3",
    )


def test_quality_report_reconciles_source_missingness_counters(
    conn: psycopg.Connection, fixture_data: CollectedScope
) -> None:
    """Source coverage counters are independent reconciliation contracts, not display metadata."""
    loader.reset_schema(conn)
    _load_fixture(conn, fixture_data)
    conn.commit()

    report = inspect(
        conn,
        ((43, 106),),
        replace(fixture_data.source_counts, shots_without_location=0),
    )

    assert "source/database mismatch for shots_without_location" in report.errors


def test_quality_report_reconciles_source_player_missingness(
    conn: psycopg.Connection, fixture_data: CollectedScope
) -> None:
    loader.reset_schema(conn)
    _load_fixture(conn, fixture_data)
    conn.commit()

    report = inspect(
        conn,
        ((43, 106),),
        replace(fixture_data.source_counts, shots_without_player=0),
    )

    assert "source/database mismatch for shots_without_attributed_player" in report.errors


def test_quality_inspection_enforces_its_own_read_only_transaction(
    conn: psycopg.Connection, fixture_data: CollectedScope
) -> None:
    loader.reset_schema(conn)
    _load_fixture(conn, fixture_data)
    conn.commit()

    inspect(conn, ((43, 106),), fixture_data.source_counts)

    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        conn.execute("INSERT INTO teams (team_id, team_name) VALUES (999999, 'Forbidden')")


def test_quality_report_exposes_integrity_defects_beyond_database_constraints(
    conn: psycopg.Connection, fixture_data: CollectedScope
) -> None:
    """Every advertised post-load invariant remains observable if its DB constraint regresses."""
    loader.reset_schema(conn)
    _load_fixture(conn, fixture_data)
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE events DROP CONSTRAINT events_location_x_measured_source_bounds")
        cur.execute("ALTER TABLE events DROP CONSTRAINT events_no_provider_xg")
        cur.execute("ALTER TABLE event_relations DROP CONSTRAINT event_relations_related_event_fk")
        cur.execute("ALTER TABLE shots DROP CONSTRAINT shots_end_location_x_bounds")
        cur.execute(
            "ALTER TABLE shot_freeze_frame_players "
            "DROP CONSTRAINT shot_freeze_frame_players_location_x_bounds"
        )
        cur.execute(
            "UPDATE events SET location_x = 999, location_y = 40 WHERE event_id = "
            "'aaaaaaaa-0000-0000-0000-000000000001'"
        )
        cur.execute(
            'UPDATE events SET type_data = \'{"nested": {"statsbomb_xg": 0.5}}\' '
            "WHERE event_id = 'aaaaaaaa-0000-0000-0000-000000000001'"
        )
        cur.execute(
            "UPDATE event_relations SET related_event_id = "
            "'ffffffff-ffff-ffff-ffff-ffffffffffff' WHERE ctid = "
            "(SELECT ctid FROM event_relations WHERE source_order = 1 LIMIT 1)"
        )
        cur.execute("DELETE FROM shots WHERE event_id = 'aaaaaaaa-0000-0000-0000-000000000004'")
        cur.execute(
            "UPDATE shots SET end_location_x = 999 WHERE event_id = "
            "'aaaaaaaa-0000-0000-0000-000000000003'"
        )
        cur.execute("UPDATE shot_freeze_frame_players SET location_x = 999")
    conn.commit()

    report = inspect(conn, ((43, 106),), fixture_data.source_counts)

    expected = {
        "events_outside_raw_bounds": 1,
        "orphan_event_relations": 1,
        "provider_xg_in_residual_json": 1,
        "shot_event_detail_mismatches": 1,
        "shot_end_coordinates_outside_bounds": 1,
        "freeze_frame_coordinates_outside_bounds": 1,
    }
    assert {name: report.invariant_violations[name] for name in expected} == expected


def test_quality_report_checks_observed_category_mappings_and_lineup_event_coverage(
    conn: psycopg.Connection, fixture_data: CollectedScope
) -> None:
    loader.reset_schema(conn)
    _load_fixture(conn, fixture_data)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE shots SET outcome_id = 999, outcome_name = CASE event_id::text "
            "WHEN 'aaaaaaaa-0000-0000-0000-000000000003' THEN 'Observed A' "
            "ELSE 'Observed B' END, body_part_id = CASE event_id::text "
            "WHEN 'aaaaaaaa-0000-0000-0000-000000000003' THEN 998 ELSE 999 END, "
            "body_part_name = 'Shared Body', "
            "technique_id = 999, technique_name = CASE event_id::text "
            "WHEN 'aaaaaaaa-0000-0000-0000-000000000003' THEN 'Technique A' "
            "ELSE 'Technique B' END, shot_type_id = CASE event_id::text "
            "WHEN 'aaaaaaaa-0000-0000-0000-000000000003' THEN 998 ELSE 999 END, "
            "shot_type_name = 'Shared Type' "
            "WHERE event_id::text IN ("
            "'aaaaaaaa-0000-0000-0000-000000000003', "
            "'aaaaaaaa-0000-0000-0000-000000000004')"
        )
        cur.execute(
            "UPDATE events SET play_pattern_id = 999, play_pattern_name = CASE event_index "
            "WHEN 1 THEN 'Pattern A' ELSE 'Pattern B' END, position_id = CASE event_index "
            "WHEN 1 THEN 998 ELSE 999 END, position_name = 'Shared Position' "
            "WHERE match_id = 900001 AND event_index IN (1, 2)"
        )
        cur.execute(
            "UPDATE events SET player_id = 8004 WHERE event_id = "
            "'aaaaaaaa-0000-0000-0000-000000000002'"
        )
    conn.commit()

    report = inspect(conn, ((43, 106),), fixture_data.source_counts)

    assert report.invariant_violations["observed_category_mapping_conflicts"] == 6
    assert report.coverage["event_actors_without_same_match_team_lineup_membership_count"] >= 1
    assert (
        report.coverage["event_actors_without_same_match_team_lineup_membership_denominator"] == 5
    )
    assert any("not appearance or minutes evidence" in warning for warning in report.warnings)


def test_quality_report_counts_matches_with_no_participant_rows(
    conn: psycopg.Connection, fixture_data: CollectedScope
) -> None:
    """The two-team invariant starts from matches, so zero-child matches cannot disappear."""
    loader.reset_schema(conn)
    _load_fixture(conn, fixture_data)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO matches (
                match_id, competition_id, season_id, match_date, kick_off,
                home_team_id, away_team_id, home_score, away_score, competition_stage
            )
            SELECT 900003, competition_id, season_id, match_date, kick_off,
                   home_team_id, away_team_id, home_score, away_score, competition_stage
            FROM matches WHERE match_id = 900001
            """
        )
    conn.commit()

    report = inspect(
        conn,
        ((43, 106),),
        replace(fixture_data.source_counts, matches=3),
    )

    assert report.invariant_violations["matches_without_exactly_two_teams"] == 1


def test_quality_report_exposes_time_and_category_pair_violations(
    conn: psycopg.Connection, fixture_data: CollectedScope
) -> None:
    """Report evidence names DB-enforced time bounds and pipeline category-pair validity."""
    loader.reset_schema(conn)
    _load_fixture(conn, fixture_data)
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE events DROP CONSTRAINT events_second_valid")
        cur.execute("UPDATE events SET second = 99 WHERE event_index = 1 AND match_id = 900001")
        cur.execute(
            "UPDATE shots SET outcome_id = NULL "
            "WHERE event_id = 'aaaaaaaa-0000-0000-0000-000000000003'"
        )
        cur.execute(
            "UPDATE events SET play_pattern_id = NULL "
            "WHERE event_id = 'aaaaaaaa-0000-0000-0000-000000000002'"
        )
    conn.commit()

    report = inspect(conn, ((43, 106),), fixture_data.source_counts)

    assert report.invariant_violations["events_outside_time_bounds"] == 1
    assert report.invariant_violations["shot_category_id_name_mismatches"] == 1
    assert report.invariant_violations["event_category_id_name_mismatches"] == 1


def test_quality_report_preserves_the_measured_event_x_exception(
    conn: psycopg.Connection, fixture_data: CollectedScope
) -> None:
    loader.reset_schema(conn)
    _load_fixture(conn, fixture_data)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE events SET location_x = 120.1, location_y = 40 "
            "WHERE event_id = 'aaaaaaaa-0000-0000-0000-000000000001'"
        )
    conn.commit()

    report = inspect(conn, ((43, 106),), fixture_data.source_counts)

    assert report.coverage["events_at_measured_x_120_1_count"] == 1
    assert any("120.1 accepted" in warning for warning in report.warnings)


def test_quality_manifest_selection_uses_relational_scope_evidence(
    conn: psycopg.Connection,
) -> None:
    """Scope identity is order-independent and comes from ingestion_run_scopes, not JSON."""
    loader.reset_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_runs (
                run_id, owner_token, source_commit, status, scopes, finished_at,
                owner_host, owner_pid, current_phase, attempted_counts
            ) VALUES (
                '00000000-0000-0000-0000-000000000011',
                '00000000-0000-0000-0000-000000000012',
                'b0bc9f22dd77c206ddedc1d742893b3bbe64baec',
                'succeeded', '[]'::jsonb, CURRENT_TIMESTAMP,
                'fixture-host', 1, 'completed', '{"matches": 2}'::jsonb
            )
            """
        )
        cur.executemany(
            "INSERT INTO ingestion_run_scopes "
            "(run_id, competition_id, season_id) VALUES (%s, %s, %s)",
            [
                ("00000000-0000-0000-0000-000000000011", 43, 106),
                ("00000000-0000-0000-0000-000000000011", 55, 282),
            ],
        )
    conn.commit()

    run_id, source_counts = _latest_matching_manifest(conn, ((55, 282), (43, 106)))

    assert run_id == "00000000-0000-0000-0000-000000000011"
    assert source_counts.matches == 2


def test_shot_detail_join_returns_location_player_team_and_outcome(
    conn: psycopg.Connection, fixture_data: CollectedScope
) -> None:
    """The join the whole schema exists to support.

    Also pins the LEFT JOIN on players: the fixture holds one shot with no attributed player, and
    an INNER JOIN would drop it and quietly change the shot count away from the source.
    """
    loader.reset_schema(conn)
    _load_fixture(conn, fixture_data)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT e.event_id::text, shooting.team_name, opponent.team_name, p.player_name,
                   e.location_x, e.location_y, s.outcome_name, s.shot_type_name
            FROM shots AS s
            JOIN events AS e ON e.event_id = s.event_id
            JOIN matches AS m ON m.match_id = e.match_id
            JOIN teams AS shooting ON shooting.team_id = e.team_id
            JOIN teams AS opponent ON opponent.team_id = CASE
                     WHEN e.team_id = m.home_team_id THEN m.away_team_id ELSE m.home_team_id END
            LEFT JOIN players AS p ON p.player_id = e.player_id
            ORDER BY e.event_id
        """)
        rows = cur.fetchall()

    assert len(rows) == EXPECTED.shots, "the LEFT JOIN must not drop the unattributed shot"

    goal = next(r for r in rows if r[0].endswith("003"))
    assert goal[1] == "Fixture United"
    assert goal[2] == "Fixture Rovers"
    assert goal[3] == "Bea Striker"
    assert (goal[4], goal[5]) == (112.0, 40.0)
    assert goal[6] == "Goal"

    unattributed = next(r for r in rows if r[0].endswith("006"))
    assert unattributed[3] is None
    assert unattributed[7] == "Penalty"

    no_location = next(r for r in rows if r[0].endswith("005"))
    assert (no_location[4], no_location[5]) == (None, None)


def test_full_fixture_loads_lineup_event_relation_possession_and_freeze_detail(
    conn: psycopg.Connection, fixture_data: CollectedScope
) -> None:
    """The committed fixture exercises every WP1.2 entity family, not a legacy shot-only seam."""
    loader.reset_schema(conn)
    _load_fixture(conn, fixture_data)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT lm.jersey_number, lp.source_order, lc.card_type
            FROM lineup_memberships AS lm
            JOIN lineup_positions AS lp USING (match_id, team_id, player_id)
            JOIN lineup_cards AS lc USING (match_id, team_id, player_id)
            WHERE lm.player_id = 8001
            """
        )
        assert cur.fetchone() == (8, 1, "Yellow Card")

        cur.execute(
            """
            SELECT p.team_id, e.type_data, count(r.related_event_id)
            FROM events AS e
            JOIN possessions AS p USING (match_id, possession_id)
            LEFT JOIN event_relations AS r ON r.source_event_id = e.event_id
            WHERE e.event_id = 'aaaaaaaa-0000-0000-0000-000000000002'
            GROUP BY p.team_id, e.type_data
            """
        )
        row = cur.fetchone()
        assert row is not None
        possession_team, type_data, relation_count = row
        assert possession_team == 7001
        assert type_data == {"pass": {"height": {"id": 1, "name": "Ground Pass"}}}
        assert relation_count == 1
        assert "statsbomb_xg" not in str(type_data)

        cur.execute(
            """
            SELECT s.key_pass_event_id::text, s.end_location_z, f.player_id, f.teammate
            FROM shots AS s
            JOIN shot_freeze_frame_players AS f USING (event_id)
            WHERE s.event_id = 'aaaaaaaa-0000-0000-0000-000000000003'
            """
        )
        assert cur.fetchone() == (
            "aaaaaaaa-0000-0000-0000-000000000002",
            1.2,
            8003,
            False,
        )


def test_failed_reconciliation_leaves_nothing_committed(
    conn: psycopg.Connection, fixture_data: CollectedScope
) -> None:
    """The contract that transaction ownership exists for.

    Rows are written, counted, found not to match, and the transaction is abandoned. Nothing
    durable may remain - otherwise reconciliation would be a report about data already kept.
    """
    wrong_source_counts = SourceCounts(
        matches=999, shots=999, shots_without_location=0, shots_without_player=0
    )

    loader.reset_schema(conn)
    _load_fixture(conn, fixture_data)
    db_counts = loader.count_rows(conn)

    assert db_counts == EXPECTED, "rows are visible inside the transaction"
    assert reconcile(wrong_source_counts, db_counts) is False

    conn.rollback()

    with pytest.raises(psycopg.errors.UndefinedTable):
        _counts_in_new_transaction()


def test_error_midway_leaves_nothing_committed(
    conn: psycopg.Connection, fixture_data: CollectedScope
) -> None:
    """A real database failure partway through a load must discard the earlier tables too.

    The failure is genuine, not simulated: the player list is given a duplicate id, so the COPY
    into `players` violates the primary key. The loader writes competitions and teams before it
    reaches players, so by the time this raises, two tables already hold rows in this transaction.

    That ordering is asserted rather than assumed - the constraint name in the error identifies
    exactly which stage failed.
    """
    duplicated_players = [*fixture_data.players, fixture_data.players[0]]

    loader.reset_schema(conn)

    with pytest.raises(psycopg.errors.UniqueViolation) as exc_info:
        loader.load_all(
            conn,
            competitions=fixture_data.competitions,
            teams=fixture_data.teams,
            players=duplicated_players,
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

    assert exc_info.value.diag.constraint_name == "players_pkey", (
        "the failure must be the players COPY, which the loader only reaches after competitions "
        "and teams have already been written in this transaction"
    )

    # PostgreSQL aborts the whole transaction on a failed statement, so the earlier writes are
    # already unreachable rather than merely unwanted.
    with pytest.raises(psycopg.errors.InFailedSqlTransaction):
        loader.count_rows(conn)

    conn.rollback()

    with pytest.raises(psycopg.errors.UndefinedTable):
        _counts_in_new_transaction()


def test_reconciliation_error_is_raised_inside_the_transaction() -> None:
    """The CLI signals a mismatch by raising, which is what triggers the rollback."""
    assert issubclass(ReconciliationError, RuntimeError)


def test_loading_into_a_populated_schema_is_refused(
    conn: psycopg.Connection, fixture_data: CollectedScope
) -> None:
    """The loader must refuse rather than duplicate.

    This is what makes "not idempotent" safe to ship: an explicit message naming the fix, not a
    duplicate-key traceback and not silently doubled counts.
    """
    loader.reset_schema(conn)
    _load_fixture(conn, fixture_data)

    with pytest.raises(loader.NotIdempotentError, match="not idempotent"):
        loader.load_all(
            conn,
            competitions=[Competition(43, 106, "FIFA World Cup", "2022", "International")],
            teams=[],
            players=[],
            matches=[],
            shots=[],
            lineups=[],
            memberships=[],
            positions=[],
            cards=[],
            possessions=[],
            events=[],
            relations=[],
            freeze_frames=[],
        )
