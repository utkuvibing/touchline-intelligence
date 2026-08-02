"""Slow, opt-in acceptance proof over the complete pinned WP1.3 source."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import psycopg
import pytest

from touchline.baseline import compute_base_rate
from touchline.ingest.cli import CollectedScope, collect
from touchline.ingest.load import load_all
from touchline.ingest.migrate import apply_migrations, read_migrations
from touchline.ingest.run import CORE_COHORT, run_ingestion
from touchline.ingest.source import SOURCE_COMMIT, StatsBombSource
from touchline.shots import fetch_shots

DB_URL = os.environ.get("TOUCHLINE_DB_URL")
FULL_SOURCE = os.environ.get("TOUCHLINE_FULL_SOURCE") == "1"
CACHE = Path("data/statsbomb") / SOURCE_COMMIT[:12]
WP21_COHORT_SQL = Path("backend/sql/wp2_1/01_model_shot_cohort.sql")
TEST_SCHEMA = "wp13_full_source_acceptance"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.full_source,
    pytest.mark.skipif(DB_URL is None, reason="TOUCHLINE_DB_URL is not set"),
    pytest.mark.skipif(
        not FULL_SOURCE,
        reason="set TOUCHLINE_FULL_SOURCE=1 to run the cached 230-match acceptance proof",
    ),
    pytest.mark.skipif(not CACHE.exists(), reason="the pinned full-source cache is absent"),
]


def _factory() -> psycopg.Connection:
    assert DB_URL is not None
    connection = psycopg.connect(DB_URL)
    with connection.cursor() as cur:
        cur.execute(f'SET search_path TO "{TEST_SCHEMA}"')
    connection.commit()
    return connection


@pytest.fixture
def populated_wp12() -> Iterator[tuple[Callable[[], psycopg.Connection], CollectedScope]]:
    """Build the committed 0005 schema and load the real WC 2022 source without a manifest."""
    assert DB_URL is not None
    with psycopg.connect(DB_URL) as conn, conn.cursor() as cur:
        cur.execute(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE')
        cur.execute(f'CREATE SCHEMA "{TEST_SCHEMA}"')
        cur.execute(f'SET search_path TO "{TEST_SCHEMA}"')
        cur.execute(
            """
            CREATE TABLE schema_migrations (
                version text PRIMARY KEY,
                checksum text NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
                applied_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        for migration in read_migrations()[:5]:
            cur.execute(migration.sql)
            cur.execute(
                "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                (migration.version, migration.checksum),
            )
        conn.commit()

    source = StatsBombSource(offline=True)
    wc_2022 = collect(source, 43, 106)
    with _factory() as conn:
        load_all(
            conn,
            competitions=wc_2022.competitions,
            teams=wc_2022.teams,
            players=wc_2022.players,
            matches=wc_2022.matches,
            shots=wc_2022.shots,
            lineups=wc_2022.lineups,
            memberships=wc_2022.memberships,
            positions=wc_2022.positions,
            cards=wc_2022.cards,
            possessions=wc_2022.possessions,
            events=wc_2022.events,
            relations=wc_2022.relations,
            freeze_frames=wc_2022.freeze_frames,
            allow_non_empty=True,
        )
        conn.commit()
        assert apply_migrations(conn) == (
            "0006_ingestion_runs",
            "0007_measured_event_x_boundary",
        )
        conn.commit()

    try:
        yield _factory, wc_2022
    finally:
        with psycopg.connect(DB_URL) as conn, conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{TEST_SCHEMA}" CASCADE')
            conn.commit()


def _fingerprint(cur: psycopg.Cursor, from_sql: str) -> tuple[int, int | None]:
    cur.execute(f"SELECT count(*), bit_xor(hashtextextended(to_jsonb(x)::text, 0)) FROM {from_sql}")
    row = cur.fetchone()
    assert row is not None
    return int(row[0]), None if row[1] is None else int(row[1])


def _wc_fingerprints(conn: psycopg.Connection) -> dict[str, tuple[int, int | None]]:
    scope = "m.competition_id = 43 AND m.season_id = 106"
    queries = {
        "matches": f"matches AS x JOIN matches AS m USING (match_id) WHERE {scope}",
        "match_teams": f"match_teams AS x JOIN matches AS m USING (match_id) WHERE {scope}",
        "lineups": f"lineups AS x JOIN matches AS m USING (match_id) WHERE {scope}",
        "lineup_memberships": (
            f"lineup_memberships AS x JOIN matches AS m USING (match_id) WHERE {scope}"
        ),
        "lineup_positions": (
            f"lineup_positions AS x JOIN matches AS m USING (match_id) WHERE {scope}"
        ),
        "lineup_cards": f"lineup_cards AS x JOIN matches AS m USING (match_id) WHERE {scope}",
        "possessions": f"possessions AS x JOIN matches AS m USING (match_id) WHERE {scope}",
        "events": f"events AS x JOIN matches AS m USING (match_id) WHERE {scope}",
        "event_relations": (
            f"event_relations AS x JOIN matches AS m USING (match_id) WHERE {scope}"
        ),
        "shots": (
            "shots AS x JOIN events AS e ON e.event_id = x.event_id "
            f"JOIN matches AS m USING (match_id) WHERE {scope}"
        ),
        "shot_freeze_frame_players": (
            "shot_freeze_frame_players AS x JOIN events AS e ON e.event_id = x.event_id "
            f"JOIN matches AS m USING (match_id) WHERE {scope}"
        ),
    }
    with conn.cursor() as cur:
        return {name: _fingerprint(cur, query) for name, query in queries.items()}


def _cohort_fingerprints(conn: psycopg.Connection) -> dict[str, tuple[int, int | None]]:
    """Fingerprint source-owned rows in every table for the exact four-tournament cohort."""
    scope = "(m.competition_id, m.season_id) IN ((43, 3), (55, 43), (43, 106), (55, 282))"
    queries = {
        "competitions": "competitions AS x WHERE x.competition_id IN (43, 55)",
        "seasons": "seasons AS x WHERE x.season_id IN (3, 43, 106, 282)",
        "competition_seasons": (
            "competition_seasons AS x WHERE (x.competition_id, x.season_id) "
            "IN ((43, 3), (55, 43), (43, 106), (55, 282))"
        ),
        # This acceptance schema starts from WC 2022 and is extended only by CORE_COHORT, so all
        # shared dimension rows belong to the declared cohort.
        "teams": "teams AS x",
        "players": "players AS x",
        "matches": f"matches AS x JOIN matches AS m USING (match_id) WHERE {scope}",
        "match_teams": f"match_teams AS x JOIN matches AS m USING (match_id) WHERE {scope}",
        "lineups": f"lineups AS x JOIN matches AS m USING (match_id) WHERE {scope}",
        "lineup_memberships": (
            f"lineup_memberships AS x JOIN matches AS m USING (match_id) WHERE {scope}"
        ),
        "lineup_positions": (
            f"lineup_positions AS x JOIN matches AS m USING (match_id) WHERE {scope}"
        ),
        "lineup_cards": f"lineup_cards AS x JOIN matches AS m USING (match_id) WHERE {scope}",
        "possessions": f"possessions AS x JOIN matches AS m USING (match_id) WHERE {scope}",
        "events": f"events AS x JOIN matches AS m USING (match_id) WHERE {scope}",
        "event_relations": (
            f"event_relations AS x JOIN matches AS m USING (match_id) WHERE {scope}"
        ),
        "shots": (
            "shots AS x JOIN events AS e ON e.event_id = x.event_id "
            f"JOIN matches AS m USING (match_id) WHERE {scope}"
        ),
        "shot_freeze_frame_players": (
            "shot_freeze_frame_players AS x JOIN events AS e ON e.event_id = x.event_id "
            f"JOIN matches AS m USING (match_id) WHERE {scope}"
        ),
    }
    with conn.cursor() as cur:
        return {name: _fingerprint(cur, query) for name, query in queries.items()}


def test_populated_wc_extends_and_identical_full_rerun_changes_no_facts(
    populated_wp12: tuple[Callable[[], psycopg.Connection], CollectedScope],
) -> None:
    """Exercise the real upgrade, merge, public boundary, reconciliation and no-op rerun."""
    factory, wc_2022 = populated_wp12
    with factory() as conn:
        wc_before = _wc_fingerprints(conn)

    first = run_ingestion(factory, StatsBombSource(offline=True), CORE_COHORT)
    assert first.source_counts == {
        "competitions": 2,
        "seasons": 4,
        "competition_seasons": 4,
        "teams": 54,
        "players": 1989,
        "matches": 230,
        "match_teams": 460,
        "lineups": 460,
        "lineup_memberships": 11062,
        "lineup_positions": 9615,
        "lineup_cards": 825,
        "possessions": 39262,
        "events": 843050,
        "event_relations": 1227110,
        "shots": 5829,
        "shot_freeze_frame_players": 78866,
        "shots_without_location": 0,
        "shots_without_player": 0,
    }
    assert first.entity_counts["events"]["unchanged"] == wc_2022.source_counts.events
    assert first.entity_counts["shots"]["unchanged"] == wc_2022.source_counts.shots

    with factory() as conn:
        assert _wc_fingerprints(conn) == wc_before
        cohort_after_first = _cohort_fingerprints(conn)
        assert set(cohort_after_first) == set(first.entity_counts)
        assert {name: fingerprint[0] for name, fingerprint in cohort_after_first.items()} == (
            {name: first.source_counts[name] for name in cohort_after_first}
        )
        baseline = compute_base_rate(conn)
        page = fetch_shots(conn, limit=1)
        assert (baseline.goals, baseline.shots) == (152, 1430)
        assert page.total == 1494
        with conn.cursor() as cur:
            cur.execute(
                "SELECT location_x FROM events "
                "WHERE event_id = '78116cc8-afbe-4bae-975b-57ce6983d045'"
            )
            assert cur.fetchone() == (120.1,)
            cur.execute(
                "SELECT count(*) FROM events WHERE type_data IS NOT NULL "
                "AND jsonb_path_exists(type_data, '$.**.statsbomb_xg')"
            )
            assert cur.fetchone() == (0,)
            cur.execute(WP21_COHORT_SQL.read_text(encoding="utf-8"))
            wp21_rows = cur.fetchall()
            assert len(wp21_rows) == 5606
            assert sum(int(row[-1]) for row in wp21_rows) == 507
            assert len({row[0] for row in wp21_rows}) == len(wp21_rows)

    second = run_ingestion(factory, StatsBombSource(offline=True), CORE_COHORT)
    assert all(
        counts["inserted"] == 0
        and counts["updated"] == 0
        and counts["unchanged"] == counts["source"] == counts["final_scoped"]
        for counts in second.entity_counts.values()
    )
    with factory() as conn:
        assert _wc_fingerprints(conn) == wc_before
        assert _cohort_fingerprints(conn) == cohort_after_first
