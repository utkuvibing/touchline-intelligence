"""Independent, read-only WP1.4 data-quality and reconciliation reporting."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

import psycopg

from touchline.ingest.cli import SourceCounts
from touchline.ingest.source import SOURCE_COMMIT

Scope = tuple[tuple[int, int], ...]
PERSISTED_GRAINS = (
    "competitions",
    "seasons",
    "competition_seasons",
    "teams",
    "players",
    "matches",
    "match_teams",
    "lineups",
    "lineup_memberships",
    "lineup_positions",
    "lineup_cards",
    "possessions",
    "events",
    "event_relations",
    "shots",
    "shot_freeze_frame_players",
)


@dataclass(frozen=True, slots=True)
class QualityReport:
    """Stable report contract, deliberately separating observation types."""

    scope: Scope
    source_commit: str
    manifest_run_id: str | None
    source_counts: Mapping[str, int]
    database_counts: Mapping[str, int]
    invariant_violations: Mapping[str, int]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    coverage: Mapping[str, int]
    exclusions: Mapping[str, str]
    limitations: tuple[str, ...]
    db_execution_status: str
    attribution: str = "Data provided by StatsBomb."

    def to_json(self) -> str:
        payload = asdict(self)
        payload["scope"] = [list(pair) for pair in self.scope]
        return json.dumps(payload, sort_keys=True, indent=2) + "\n"


def render_text(report: QualityReport) -> str:
    """Render the same facts for a terminal reader without conflating severity classes."""

    def section(name: str, values: Sequence[str]) -> list[str]:
        return [name, *(f"  {value}" for value in values)] if values else [name, "  none"]

    lines = [
        "Touchline WP1.4 data-quality report",
        f"Database execution: {report.db_execution_status}",
        f"Source commit: {report.source_commit}",
        f"Successful ingestion manifest: {report.manifest_run_id or 'not supplied'}",
        "Scope: " + ", ".join(f"{competition}/{season}" for competition, season in report.scope),
        *section("Errors", report.errors),
        *section("Warnings", report.warnings),
        "Reconciliation (source, database, status)",
        *(
            f"  {name}: {report.source_counts[name]}, {report.database_counts[name]}, "
            f"{'OK' if report.source_counts[name] == report.database_counts[name] else 'MISMATCH'}"
            for name in PERSISTED_GRAINS
        ),
        "Invariant violations (count, status)",
        *(
            f"  {name}: {count}, {'OK' if count == 0 else 'VIOLATION'}"
            for name, count in sorted(report.invariant_violations.items())
        ),
        "Coverage (count, denominator, basis points)",
        *(f"  {key}: {value}" for key, value in sorted(report.coverage.items())),
        "Exclusions",
        *(f"  {key}: {value}" for key, value in sorted(report.exclusions.items())),
        *section("Known limitations", report.limitations),
        report.attribution,
    ]
    return "\n".join(lines) + "\n"


def _cte(scope: Scope) -> tuple[str, list[int]]:
    values = ", ".join(["(%s, %s)"] * len(scope))
    params = [value for pair in scope for value in pair]
    return (
        "WITH scoped(competition_id, season_id) AS "
        f"(VALUES {values}), scoped_matches AS ("
        "SELECT m.* FROM matches m JOIN scoped s USING (competition_id, season_id)) ",
        params,
    )


def _scoped_counts(conn: psycopg.Connection, scope: Scope) -> dict[str, int]:
    """Count each persisted source grain within exactly the requested competition-seasons."""

    joins = {
        "competitions": (
            "competitions c JOIN (SELECT DISTINCT competition_id FROM scoped) q "
            "USING (competition_id)"
        ),
        "seasons": "seasons s JOIN (SELECT DISTINCT season_id FROM scoped) q USING (season_id)",
        "competition_seasons": (
            "competition_seasons cs JOIN scoped q USING (competition_id, season_id)"
        ),
        "teams": (
            "teams t JOIN (SELECT DISTINCT team_id FROM match_teams "
            "JOIN scoped_matches USING (match_id)) q USING (team_id)"
        ),
        "players": (
            "players p JOIN (SELECT DISTINCT player_id FROM ("
            "SELECT player_id FROM lineup_memberships JOIN scoped_matches USING (match_id) "
            "UNION SELECT player_id FROM events JOIN scoped_matches USING (match_id)) ids "
            "WHERE player_id IS NOT NULL) q USING (player_id)"
        ),
        "matches": "scoped_matches",
        "match_teams": "match_teams JOIN scoped_matches USING (match_id)",
        "lineups": "lineups JOIN scoped_matches USING (match_id)",
        "lineup_memberships": "lineup_memberships JOIN scoped_matches USING (match_id)",
        "lineup_positions": "lineup_positions JOIN scoped_matches USING (match_id)",
        "lineup_cards": "lineup_cards JOIN scoped_matches USING (match_id)",
        "possessions": "possessions JOIN scoped_matches USING (match_id)",
        "events": "events JOIN scoped_matches USING (match_id)",
        "event_relations": "event_relations JOIN scoped_matches USING (match_id)",
        "shots": "shots JOIN events USING (event_id) JOIN scoped_matches USING (match_id)",
        "shot_freeze_frame_players": (
            "shot_freeze_frame_players JOIN events USING (event_id) "
            "JOIN scoped_matches USING (match_id)"
        ),
    }
    cte, params = _cte(scope)
    with conn.cursor() as cur:
        output = {}
        for name, source in joins.items():
            cur.execute(cte + f"SELECT count(*) FROM {source}", params)
            row = cur.fetchone()
            output[name] = int(row[0]) if row else 0
    return output


def _scalar(conn: psycopg.Connection, query: str, scope: Scope) -> int:
    cte, params = _cte(scope)
    with conn.cursor() as cur:
        cur.execute(cte + query, params)
        row = cur.fetchone()
    return int(row[0]) if row else 0


def _coverage(count: int, denominator: int) -> dict[str, int]:
    return {
        "count": count,
        "denominator": denominator,
        "basis_points": 0 if denominator == 0 else count * 10_000 // denominator,
    }


def inspect(
    conn: psycopg.Connection,
    scope: Scope,
    source_counts: SourceCounts,
    *,
    manifest_run_id: str | None = None,
) -> QualityReport:
    """Audit committed facts; this public seam opens no writer transaction and makes no repairs."""

    if not scope:
        raise ValueError("quality inspection needs at least one competition-season")
    conn.execute("SET TRANSACTION READ ONLY")
    database_counts = _scoped_counts(conn, scope)
    expected = {name: int(getattr(source_counts, name)) for name in PERSISTED_GRAINS}
    errors = [
        f"source/database count mismatch for {name}: {expected[name]} != {database_counts[name]}"
        for name in PERSISTED_GRAINS
        if expected[name] != database_counts[name]
    ]
    checks = {
        "matches_without_exactly_two_teams": (
            "SELECT count(*) FROM (SELECT sm.match_id FROM scoped_matches sm "
            "LEFT JOIN match_teams mt USING (match_id) GROUP BY sm.match_id "
            "HAVING count(mt.team_id) <> 2) q"
        ),
        "events_outside_time_bounds": (
            "SELECT count(*) FROM events JOIN scoped_matches USING (match_id) "
            "WHERE period NOT BETWEEN 1 AND 5 OR minute < 0 OR second NOT BETWEEN 0 AND 59 "
            "OR duration < 0"
        ),
        "events_outside_raw_bounds": (
            "SELECT count(*) FROM events JOIN scoped_matches USING (match_id) "
            "WHERE location_x < 0 OR location_x > 120.1 OR location_y < 0 OR location_y > 80"
        ),
        "orphan_event_relations": (
            "SELECT count(*) FROM event_relations r JOIN scoped_matches sm USING (match_id) "
            "LEFT JOIN events a ON (a.match_id, a.event_id) = (r.match_id, r.source_event_id) "
            "LEFT JOIN events b ON (b.match_id, b.event_id) = (r.match_id, r.related_event_id) "
            "WHERE a.event_id IS NULL OR b.event_id IS NULL"
        ),
        "provider_xg_in_residual_json": (
            "SELECT count(*) FROM events JOIN scoped_matches USING (match_id) "
            "WHERE type_data IS NOT NULL AND jsonb_path_exists(type_data, '$.**.statsbomb_xg')"
        ),
        "shot_event_detail_mismatches": (
            "SELECT count(*) FROM events e JOIN scoped_matches sm USING (match_id) "
            "LEFT JOIN shots s ON s.event_id = e.event_id "
            "WHERE (e.event_type_name = 'Shot') <> (s.event_id IS NOT NULL)"
        ),
        "shot_category_id_name_mismatches": (
            "SELECT count(*) FROM shots JOIN events USING (event_id) "
            "JOIN scoped_matches USING (match_id) WHERE "
            "(outcome_id IS NULL) <> (outcome_name IS NULL) OR "
            "(body_part_id IS NULL) <> (body_part_name IS NULL) OR "
            "(technique_id IS NULL) <> (technique_name IS NULL) OR "
            "(shot_type_id IS NULL) <> (shot_type_name IS NULL)"
        ),
        "event_category_id_name_mismatches": (
            "SELECT count(*) FROM events JOIN scoped_matches USING (match_id) WHERE "
            "(play_pattern_id IS NULL) <> (play_pattern_name IS NULL) OR "
            "(position_id IS NULL) <> (position_name IS NULL)"
        ),
        "observed_category_mapping_conflicts": (
            ", scoped_shots AS (SELECT s.* FROM shots s JOIN events e USING (event_id) "
            "JOIN scoped_matches USING (match_id)), conflicts AS ("
            "SELECT outcome_id::text FROM scoped_shots WHERE outcome_id IS NOT NULL "
            "GROUP BY outcome_id HAVING count(DISTINCT outcome_name) > 1 UNION ALL "
            "SELECT outcome_name FROM scoped_shots WHERE outcome_name IS NOT NULL "
            "GROUP BY outcome_name HAVING count(DISTINCT outcome_id) > 1 UNION ALL "
            "SELECT body_part_id::text FROM scoped_shots WHERE body_part_id IS NOT NULL "
            "GROUP BY body_part_id HAVING count(DISTINCT body_part_name) > 1 UNION ALL "
            "SELECT body_part_name FROM scoped_shots WHERE body_part_name IS NOT NULL "
            "GROUP BY body_part_name HAVING count(DISTINCT body_part_id) > 1 UNION ALL "
            "SELECT technique_id::text FROM scoped_shots WHERE technique_id IS NOT NULL "
            "GROUP BY technique_id HAVING count(DISTINCT technique_name) > 1 UNION ALL "
            "SELECT technique_name FROM scoped_shots WHERE technique_name IS NOT NULL "
            "GROUP BY technique_name HAVING count(DISTINCT technique_id) > 1 UNION ALL "
            "SELECT shot_type_id::text FROM scoped_shots WHERE shot_type_id IS NOT NULL "
            "GROUP BY shot_type_id HAVING count(DISTINCT shot_type_name) > 1 UNION ALL "
            "SELECT shot_type_name FROM scoped_shots WHERE shot_type_name IS NOT NULL "
            "GROUP BY shot_type_name HAVING count(DISTINCT shot_type_id) > 1 UNION ALL "
            "SELECT play_pattern_id::text FROM events JOIN scoped_matches USING (match_id) "
            "WHERE play_pattern_id IS NOT NULL GROUP BY play_pattern_id "
            "HAVING count(DISTINCT play_pattern_name) > 1 UNION ALL "
            "SELECT play_pattern_name FROM events JOIN scoped_matches USING (match_id) "
            "WHERE play_pattern_name IS NOT NULL GROUP BY play_pattern_name "
            "HAVING count(DISTINCT play_pattern_id) > 1 UNION ALL "
            "SELECT position_id::text FROM events JOIN scoped_matches USING (match_id) "
            "WHERE position_id IS NOT NULL GROUP BY position_id "
            "HAVING count(DISTINCT position_name) > 1 UNION ALL "
            "SELECT position_name FROM events JOIN scoped_matches USING (match_id) "
            "WHERE position_name IS NOT NULL GROUP BY position_name "
            "HAVING count(DISTINCT position_id) > 1) SELECT count(*) FROM conflicts"
        ),
        "shot_end_coordinates_outside_bounds": (
            "SELECT count(*) FROM shots JOIN events USING (event_id) "
            "JOIN scoped_matches USING (match_id) WHERE "
            "(end_location_x IS NULL) <> (end_location_y IS NULL) OR "
            "end_location_x < 0 OR end_location_x > 120 OR "
            "end_location_y < 0 OR end_location_y > 80 OR end_location_z < 0"
        ),
        "freeze_frame_coordinates_outside_bounds": (
            "SELECT count(*) FROM shot_freeze_frame_players f JOIN events e USING (event_id) "
            "JOIN scoped_matches USING (match_id) WHERE "
            "(f.location_x IS NULL) <> (f.location_y IS NULL) OR "
            "f.location_x < 0 OR f.location_x > 120 OR "
            "f.location_y < 0 OR f.location_y > 80"
        ),
    }
    invariant_violations = {name: _scalar(conn, query, scope) for name, query in checks.items()}
    for name, count in invariant_violations.items():
        if count:
            errors.append(f"{name}: {count}")

    shots = database_counts["shots"]
    events = database_counts["events"]
    memberships = database_counts["lineup_memberships"]
    values = {
        "shots_without_location": _scalar(
            conn,
            "SELECT count(*) FROM shots JOIN events USING (event_id) "
            "JOIN scoped_matches USING (match_id) WHERE location_x IS NULL",
            scope,
        ),
        "shots_without_attributed_player": _scalar(
            conn,
            "SELECT count(*) FROM shots JOIN events USING (event_id) "
            "JOIN scoped_matches USING (match_id) WHERE player_id IS NULL",
            scope,
        ),
        "shots_missing_any_future_cohort_field": _scalar(
            conn,
            "SELECT count(*) FROM shots JOIN events USING (event_id) "
            "JOIN scoped_matches USING (match_id) WHERE player_id IS NULL OR period IS NULL "
            "OR location_x IS NULL OR outcome_name IS NULL OR body_part_name IS NULL "
            "OR technique_name IS NULL OR shot_type_name IS NULL",
            scope,
        ),
        "lineup_memberships_without_position_interval": _scalar(
            conn,
            "SELECT count(*) FROM lineup_memberships lm JOIN scoped_matches USING (match_id) "
            "LEFT JOIN lineup_positions lp USING (match_id, team_id, player_id) "
            "WHERE lp.player_id IS NULL",
            scope,
        ),
        "events_at_measured_x_120_1": _scalar(
            conn,
            "SELECT count(*) FROM events JOIN scoped_matches USING (match_id) "
            "WHERE location_x = 120.1",
            scope,
        ),
        "events_without_player": _scalar(
            conn,
            "SELECT count(*) FROM events JOIN scoped_matches USING (match_id) "
            "WHERE player_id IS NULL",
            scope,
        ),
        "events_without_location": _scalar(
            conn,
            "SELECT count(*) FROM events JOIN scoped_matches USING (match_id) "
            "WHERE location_x IS NULL",
            scope,
        ),
        "events_without_position": _scalar(
            conn,
            "SELECT count(*) FROM events JOIN scoped_matches USING (match_id) "
            "WHERE position_id IS NULL",
            scope,
        ),
        "events_without_duration": _scalar(
            conn,
            "SELECT count(*) FROM events JOIN scoped_matches USING (match_id) "
            "WHERE duration IS NULL",
            scope,
        ),
        "event_actors_without_same_match_team_lineup_membership": _scalar(
            conn,
            "SELECT count(*) FROM events e JOIN scoped_matches USING (match_id) "
            "LEFT JOIN lineup_memberships lm ON (lm.match_id, lm.team_id, lm.player_id) = "
            "(e.match_id, e.team_id, e.player_id) WHERE e.player_id IS NOT NULL "
            "AND lm.player_id IS NULL",
            scope,
        ),
    }
    if values["shots_without_location"] != source_counts.shots_without_location:
        errors.append("source/database mismatch for shots_without_location")
    if values["shots_without_attributed_player"] != source_counts.shots_without_player:
        errors.append("source/database mismatch for shots_without_attributed_player")
    if values["shots_missing_any_future_cohort_field"]:
        errors.append(
            "shots missing future-cohort eligibility/feature fields: "
            f"{values['shots_missing_any_future_cohort_field']}"
        )
    coverage = {}
    event_actors = events - values["events_without_player"]
    denominators = {
        "shots_without_location": shots,
        "shots_without_attributed_player": shots,
        "shots_missing_any_future_cohort_field": shots,
        "lineup_memberships_without_position_interval": memberships,
        "events_at_measured_x_120_1": events,
        "events_without_player": events,
        "events_without_location": events,
        "events_without_position": events,
        "events_without_duration": events,
        "event_actors_without_same_match_team_lineup_membership": event_actors,
    }
    for name, count in values.items():
        for suffix, number in _coverage(count, denominators[name]).items():
            coverage[f"{name}_{suffix}"] = number
    warnings = []
    if values["events_at_measured_x_120_1"]:
        warnings.append("event coordinate exception: 120.1 accepted as the documented raw boundary")
    unmatched = values["event_actors_without_same_match_team_lineup_membership"]
    if unmatched:
        warnings.append(
            f"event actors without same-match-team lineup membership: {unmatched}; "
            "this is coverage, not appearance or minutes evidence"
        )
    return QualityReport(
        scope=scope,
        source_commit=SOURCE_COMMIT,
        manifest_run_id=manifest_run_id,
        source_counts=expected,
        database_counts=database_counts,
        invariant_violations=invariant_violations,
        errors=tuple(errors),
        warnings=tuple(warnings),
        coverage=coverage,
        exclusions={"provider_xg": "not persisted by design; report verifies residual JSON only"},
        limitations=(
            "Generic-event and lineup NULLs are observed coverage, not completeness failures.",
            "Category checks enforce observed scoped ID/name consistency, "
            "not an external taxonomy.",
            "Position intervals are preserved without inferred chronology.",
            "Lineup membership is not an appearance or minutes-played denominator.",
            "Embedded shot freeze frames are not StatsBomb 360 or continuous tracking data.",
        ),
        db_execution_status="executed",
    )
