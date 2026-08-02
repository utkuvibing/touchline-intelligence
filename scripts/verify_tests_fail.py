"""Verify that the test suite actually protects what it claims to.

A green suite proves the tests pass, not that they would fail if the behaviour broke. This script
introduces one deliberate break per protected contract, runs the relevant tests, asserts they fail,
and restores the file.

Run with a clean working tree:

    uv run python scripts/verify_tests_fail.py

It has already earned its place three times. It found that the /health liveness test passed even
when /health was made to call the database (the failure was invisible from the response body), that
the /ready secret-leak test passed for the wrong reason because its substring blocklist missed the
actual driver error, and that the read-only test configured a separate transaction instead of
observing the production query's transaction. All three tests were rewritten.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

HEALTH_ANCHOR = "    settings = get_settings()\n    return Health("
HEALTH_BROKEN = (
    "    settings = get_settings()\n"
    "    _check_database(settings)  # DELIBERATE BREAK\n"
    "    return Health("
)

DB_URL_ANCHOR = "    db_url: PostgresDsn = Field(\n        description="
DB_URL_BROKEN = (
    "    db_url: PostgresDsn = Field(\n"
    '        default="postgresql://a:b@localhost:5432/c",  # DELIBERATE BREAK\n'
    "        description="
)

OPS_TESTS = "uv run pytest backend/tests/test_ops_endpoints.py -q"
CONFIG_TESTS = "uv run pytest backend/tests/test_config.py -q"
DIRECT_DATABASE_COMMAND_TESTS = "uv run pytest backend/tests/test_ingest_command_policy.py -q"
PARSE_TESTS = "uv run pytest backend/tests/test_ingest_parse.py -q"
# Database-backed mutations only prove anything when TOUCHLINE_DB_URL is set, and the hermeticity
# break is invisible unless a TOUCHLINE_* variable is exported. The script reports MISSED otherwise,
# which is honest: an unrun test protects nothing.
LOAD_TESTS = "uv run pytest backend/tests/test_ingest_load_integration.py -q"
QUALITY_UNIT_TESTS = "uv run pytest backend/tests/test_quality.py -q"
QUALITY_TESTS = (
    "uv run pytest backend/tests/test_ingest_load_integration.py::"
    "test_independent_quality_report_reconciles_the_fixture_after_commit "
    "backend/tests/test_ingest_load_integration.py::"
    "test_quality_report_fails_an_exact_source_count_mismatch "
    "backend/tests/test_ingest_load_integration.py::"
    "test_quality_report_reconciles_source_missingness_counters "
    "backend/tests/test_ingest_load_integration.py::"
    "test_quality_report_counts_matches_with_no_participant_rows "
    "backend/tests/test_ingest_load_integration.py::"
    "test_quality_report_exposes_time_and_category_pair_violations "
    "backend/tests/test_ingest_load_integration.py::"
    "test_quality_report_reconciles_source_player_missingness "
    "backend/tests/test_ingest_load_integration.py::"
    "test_quality_inspection_enforces_its_own_read_only_transaction "
    "backend/tests/test_ingest_load_integration.py::"
    "test_quality_report_exposes_integrity_defects_beyond_database_constraints "
    "backend/tests/test_ingest_load_integration.py::"
    "test_quality_report_checks_observed_category_mappings_and_lineup_event_coverage "
    "backend/tests/test_ingest_load_integration.py::"
    "test_quality_report_preserves_the_measured_event_x_exception "
    "backend/tests/test_ingest_load_integration.py::"
    "test_quality_manifest_selection_uses_relational_scope_evidence -q"
)
QUALITY_SOURCE_PLAYER_TEST = (
    "uv run pytest backend/tests/test_ingest_load_integration.py::"
    "test_quality_report_reconciles_source_player_missingness -q"
)
QUALITY_SOURCE_LOCATION_TEST = (
    "uv run pytest backend/tests/test_ingest_load_integration.py::"
    "test_quality_report_reconciles_source_missingness_counters -q"
)
QUALITY_READ_ONLY_TEST = (
    "uv run pytest backend/tests/test_ingest_load_integration.py::"
    "test_quality_inspection_enforces_its_own_read_only_transaction -q"
)
QUALITY_INTEGRITY_DEFECT_TEST = (
    "uv run pytest backend/tests/test_ingest_load_integration.py::"
    "test_quality_report_exposes_integrity_defects_beyond_database_constraints -q"
)
QUALITY_CATEGORY_COVERAGE_TEST = (
    "uv run pytest backend/tests/test_ingest_load_integration.py::"
    "test_quality_report_checks_observed_category_mappings_and_lineup_event_coverage -q"
)
QUALITY_COVERAGE_TEST = (
    "uv run pytest backend/tests/test_ingest_load_integration.py::"
    "test_independent_quality_report_reconciles_the_fixture_after_commit -q"
)
QUALITY_X_EXCEPTION_TEST = (
    "uv run pytest backend/tests/test_ingest_load_integration.py::"
    "test_quality_report_preserves_the_measured_event_x_exception -q"
)
BASELINE_TESTS = "uv run pytest backend/tests/test_baseline_integration.py -q"
SHOTS_TESTS = "uv run pytest backend/tests/test_shots_integration.py -q"
PUBLIC_SCOPE_TESTS = (
    "uv run pytest "
    "backend/tests/test_baseline_integration.py::"
    "test_public_baseline_excludes_an_internal_cohort_tournament "
    "backend/tests/test_shots_integration.py::"
    "test_public_shots_exclude_an_internal_cohort_tournament -q"
)
MIGRATION_TESTS = "uv run pytest backend/tests/test_migrations_integration.py -q"
INGEST_RUN_TESTS = "uv run pytest backend/tests/test_ingest_run_integration.py -q"
INGEST_RERUN_TEST = (
    "uv run pytest backend/tests/test_ingest_run_integration.py::"
    "test_first_load_and_identical_rerun_are_auditable_noops -q"
)
INGEST_CONFLICT_TEST = (
    "uv run pytest backend/tests/test_ingest_run_integration.py::"
    "test_changed_match_fact_rejects_the_whole_second_data_transaction -q"
)
INGEST_ROLLBACK_TEST = (
    "uv run pytest backend/tests/test_ingest_run_integration.py::"
    "test_bad_event_after_staging_rolls_back_every_fact_and_records_failure -q"
)
INGEST_LOCK_TEST = (
    "uv run pytest backend/tests/test_ingest_run_integration.py::"
    "test_locked_active_run_is_not_reclassified_as_interrupted -q"
)
INGEST_RECOVERY_TEST = (
    "uv run pytest backend/tests/test_ingest_run_integration.py::"
    "test_next_lock_owner_recovers_abandoned_running_manifest -q"
)
INGEST_LIFECYCLE_RACE_TEST = (
    "uv run pytest backend/tests/test_ingest_run_integration.py::"
    "test_recovery_waits_for_a_contender_to_finish_its_manifest -q"
)
INGEST_SCOPE_EVIDENCE_TEST = (
    "uv run pytest backend/tests/test_migrations_integration.py::"
    "test_ingestion_scope_evidence_prevents_parent_manifest_deletion -q"
)
WP15_TESTS = "uv run pytest backend/tests/test_wp1_5_analysis_integration.py -q"
WP21_TESTS = "uv run pytest backend/tests/test_wp2_1_cohort_integration.py -q"
WP21_AVAILABILITY_TEST = (
    "uv run pytest backend/tests/test_wp2_1_cohort_integration.py::"
    "test_every_candidate_has_the_exact_availability_decision -q"
)
WP21_CATEGORY_TEST = (
    "uv run pytest backend/tests/test_wp2_1_cohort_integration.py::"
    "test_category_coverage_has_support_only_and_no_target_aggregates -q"
)
WP21_PENALTY_BREAKDOWN_TEST = (
    "uv run pytest backend/tests/test_wp2_1_cohort_integration.py::"
    "test_penalty_breakdown_is_reproducible_by_tournament -q"
)
WP21_PROJECTION_TEST = (
    "uv run pytest backend/tests/test_wp2_1_cohort_integration.py::"
    "test_cohort_projection_exposes_no_forbidden_input_columns -q"
)
WP21_REQUIRED_PREDICATES_TEST = (
    "uv run pytest backend/tests/test_wp2_1_cohort_integration.py::"
    "test_cohort_keeps_every_required_null_exclusion_explicit -q"
)
WP16_FIXTURE_MANIFEST_TESTS = "uv run pytest backend/tests/test_wp1_6_fixture_manifest.py -q"
FRONTEND_TESTS = "npm test"
SCHEMA_DRIFT_TESTS = "uv run pytest backend/tests/test_schema_drift_integration.py -q"


@dataclass(frozen=True)
class Break:
    """One deliberate defect and the command that must notice it."""

    contract: str
    path: Path
    anchor: str
    replacement: str
    command: str
    cwd: Path


QUALITY_DENOMINATOR_MUTATIONS = (
    ("shots_without_location", "shots", "events"),
    ("shots_without_attributed_player", "shots", "events"),
    ("shots_missing_any_future_cohort_field", "shots", "events"),
    ("lineup_memberships_without_position_interval", "memberships", "events"),
    ("events_at_measured_x_120_1", "events", "shots"),
    ("events_without_player", "events", "shots"),
    ("events_without_location", "events", "shots"),
    ("events_without_position", "events", "shots"),
    ("events_without_duration", "events", "shots"),
    ("event_actors_without_same_match_team_lineup_membership", "event_actors", "events"),
)


BREAKS: list[Break] = [
    Break(
        contract="WP2.1 model cohort must exclude Penalty shot types",
        path=ROOT / "backend/sql/wp2_1/01_model_shot_cohort.sql",
        anchor="  AND s.shot_type_name <> 'Penalty'\n",
        replacement="  AND true -- DELIBERATE BREAK\n",
        command=WP21_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.1 model cohort must independently exclude period five",
        path=ROOT / "backend/sql/wp2_1/01_model_shot_cohort.sql",
        anchor="  AND e.period <> 5\n",
        replacement="  AND true -- DELIBERATE BREAK\n",
        command=WP21_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.1 target must map only recorded Goal outcomes to one",
        path=ROOT / "backend/sql/wp2_1/01_model_shot_cohort.sql",
        anchor="    CASE WHEN s.outcome_name = 'Goal' THEN 1 ELSE 0 END AS is_goal\n",
        replacement=(
            "    CASE WHEN s.outcome_name = 'Saved' THEN 1 ELSE 0 END AS is_goal "
            "-- DELIBERATE BREAK\n"
        ),
        command=WP21_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.1 cohort must independently require a known x coordinate",
        path=ROOT / "backend/sql/wp2_1/01_model_shot_cohort.sql",
        anchor="  AND e.location_x IS NOT NULL\n",
        replacement="  AND true -- DELIBERATE BREAK\n",
        command=WP21_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.1 cohort must independently require a known y coordinate",
        path=ROOT / "backend/sql/wp2_1/01_model_shot_cohort.sql",
        anchor="  AND e.location_y IS NOT NULL\n",
        replacement="  AND true -- DELIBERATE BREAK\n",
        command=WP21_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.1 cohort projection must reject post-event fields",
        path=ROOT / "backend/sql/wp2_1/01_model_shot_cohort.sql",
        anchor="    e.under_pressure,\n",
        replacement="    e.under_pressure,\n    e.duration, -- DELIBERATE BREAK\n",
        command=WP21_PROJECTION_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.1 cohort must keep the explicit e.player_id NULL exclusion",
        path=ROOT / "backend/sql/wp2_1/01_model_shot_cohort.sql",
        anchor="WHERE e.player_id IS NOT NULL\n",
        replacement="WHERE true -- DELIBERATE BREAK\n",
        command=WP21_REQUIRED_PREDICATES_TEST,
        cwd=ROOT,
    ),
    *(
        Break(
            contract=f"WP2.1 cohort must keep the explicit {field} NULL exclusion",
            path=ROOT / "backend/sql/wp2_1/01_model_shot_cohort.sql",
            anchor=f"  AND {field} IS NOT NULL\n",
            replacement="  AND true -- DELIBERATE BREAK\n",
            command=WP21_REQUIRED_PREDICATES_TEST,
            cwd=ROOT,
        )
        for field in (
            "e.period",
            "s.outcome_name",
            "s.body_part_name",
            "s.technique_name",
            "s.shot_type_name",
        )
    ),
    Break(
        contract="WP2.1 category coverage must report exact support",
        path=ROOT / "backend/sql/wp2_1/03_category_coverage.sql",
        anchor="    count(*) AS shots\n",
        replacement="    count(*) + 1 AS shots -- DELIBERATE BREAK\n",
        command=WP21_CATEGORY_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.1 tournament penalty evidence must remain reproducible",
        path=ROOT / "backend/sql/wp2_1/04_penalty_breakdown.sql",
        anchor=") AS regulation_penalties,\n",
        replacement=") + 1 AS regulation_penalties, -- DELIBERATE BREAK\n",
        command=WP21_PENALTY_BREAKDOWN_TEST,
        cwd=ROOT,
    ),
    *(
        Break(
            contract=f"WP2.1 leakage table must classify {candidate} as Unavailable",
            path=ROOT / "docs/modeling/wp2_1-cohort-and-leakage-contract.md",
            anchor=f"| {candidate} | Unavailable |",
            replacement=f"| {candidate} | Available | <!-- DELIBERATE BREAK -->",
            command=WP21_AVAILABILITY_TEST,
            cwd=ROOT,
        )
        for candidate in (
            "Outcome ID/name",
            "Shot end `x/y/z`",
            "Provider `statsbomb_xg`",
            "Future events, final score, later match state",
        )
    ),
    Break(
        contract="WP1.6 fixture manifest must pin the exact fictional source bytes",
        path=ROOT / "data/fixtures/statsbomb/manifest.json",
        anchor="99f9297a5a83b392dbbff9ce6f025bc0cf6ee5a5a4d86362a4b095c1312ee766",
        replacement="0000000000000000000000000000000000000000000000000000000000000000",
        command=WP16_FIXTURE_MANIFEST_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP1.5 competition coverage must report zero teams for an empty declared scope",
        path=ROOT / "backend/sql/wp1_5/01_competition_coverage.sql",
        anchor="    coalesce(tc.team_count, 0) AS team_count,",
        replacement="    tc.team_count,  -- DELIBERATE BREAK",
        command=WP15_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP1.5 descriptive prevalence must exclude penalties",
        path=ROOT / "backend/sql/wp1_5/05_shot_prevalence.sql",
        anchor="  AND s.shot_type_name <> 'Penalty'\n",
        replacement="  AND true -- DELIBERATE BREAK\n",
        command=WP15_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP1.5 lineup evidence must preserve memberships with no supporting evidence",
        path=ROOT / "backend/sql/wp1_5/09_lineup_participation_evidence.sql",
        anchor="LEFT JOIN position_evidence AS pe USING (match_id, team_id, player_id)",
        replacement=(
            "JOIN position_evidence AS pe USING (match_id, team_id, player_id) -- DELIBERATE BREAK"
        ),
        command=WP15_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP1.5 sequence must order events by their recorded source index",
        path=ROOT / "backend/sql/wp1_5/10_pre_shot_event_sequence.sql",
        anchor="            ORDER BY event_index\n",
        replacement="            ORDER BY event_index DESC -- DELIBERATE BREAK\n",
        command=WP15_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="generated quality reports must carry StatsBomb attribution",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor='attribution: str = "Data provided by StatsBomb."',
        replacement='attribution: str = "Attribution omitted"  # DELIBERATE BREAK',
        command=QUALITY_UNIT_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="the committed manual sampling checklist must carry StatsBomb attribution",
        path=ROOT / "reports/wp1.4-sampling-checklist.md",
        anchor="Data provided by StatsBomb.",
        replacement="Attribution omitted.  <!-- DELIBERATE BREAK -->",
        command=QUALITY_UNIT_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="quality coverage must calculate integer basis points from count/denominator",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor=(
            '        "basis_points": 0 if denominator == 0 else count * 10_000 // denominator,'
        ),
        replacement=(
            '        "basis_points": 0 if denominator == 0 else count * 1_000 // denominator,'
            "  # DELIBERATE BREAK"
        ),
        command=QUALITY_COVERAGE_TEST,
        cwd=ROOT,
    ),
    *(
        Break(
            contract=f"quality coverage denominator for {metric} must remain {denominator}",
            path=ROOT / "backend/src/touchline/quality.py",
            anchor=f'        "{metric}": {denominator},',
            replacement=f'        "{metric}": {wrong},  # DELIBERATE BREAK',
            command=QUALITY_COVERAGE_TEST,
            cwd=ROOT,
        )
        for metric, denominator, wrong in QUALITY_DENOMINATOR_MUTATIONS
    ),
    Break(
        contract="quality reconciliation must report a source/database count mismatch",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor=("        if expected[name] != database_counts[name]\n    ]"),
        replacement=("        if False  # DELIBERATE BREAK\n    ]"),
        command=QUALITY_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="quality must reconcile source shot-location missingness",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor='if values["shots_without_location"] != source_counts.shots_without_location:',
        replacement="if False:  # DELIBERATE BREAK",
        command=QUALITY_SOURCE_LOCATION_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="quality must reconcile source shot-player missingness",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor=(
            'if values["shots_without_attributed_player"] != source_counts.shots_without_player:'
        ),
        replacement="if False:  # DELIBERATE BREAK",
        command=QUALITY_SOURCE_PLAYER_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="quality inspection must enforce its own read-only transaction",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor='    conn.execute("SET TRANSACTION READ ONLY")',
        replacement="    pass  # DELIBERATE BREAK",
        command=QUALITY_READ_ONLY_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="quality reporting must detect raw event coordinate violations",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor='"WHERE location_x < 0 OR location_x > 120.1 OR location_y < 0 OR location_y > 80"',
        replacement='"WHERE false"  # DELIBERATE BREAK',
        command=QUALITY_INTEGRITY_DEFECT_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="quality reporting must detect orphan event relations",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor='"WHERE a.event_id IS NULL OR b.event_id IS NULL"',
        replacement='"WHERE false"  # DELIBERATE BREAK',
        command=QUALITY_INTEGRITY_DEFECT_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="quality reporting must detect provider xG in residual JSON",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor=(
            "\"WHERE type_data IS NOT NULL AND jsonb_path_exists(type_data, '$.**.statsbomb_xg')\""
        ),
        replacement='"WHERE false"  # DELIBERATE BREAK',
        command=QUALITY_INTEGRITY_DEFECT_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="quality reporting must reconcile Shot events and typed details",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor="\"WHERE (e.event_type_name = 'Shot') <> (s.event_id IS NOT NULL)\"",
        replacement='"WHERE false"  # DELIBERATE BREAK',
        command=QUALITY_INTEGRITY_DEFECT_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="quality reporting must detect observed category mapping conflicts",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor='"GROUP BY outcome_id HAVING count(DISTINCT outcome_name) > 1 UNION ALL "',
        replacement='"GROUP BY outcome_id HAVING false UNION ALL "  # DELIBERATE BREAK',
        command=QUALITY_CATEGORY_COVERAGE_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="quality reporting must detect reverse shot category mapping conflicts",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor='"GROUP BY body_part_name HAVING count(DISTINCT body_part_id) > 1 UNION ALL "',
        replacement='"GROUP BY body_part_name HAVING false UNION ALL "  # DELIBERATE BREAK',
        command=QUALITY_CATEGORY_COVERAGE_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="quality reporting must detect event category mapping conflicts",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor='"HAVING count(DISTINCT play_pattern_name) > 1 UNION ALL "',
        replacement='"HAVING false UNION ALL "  # DELIBERATE BREAK',
        command=QUALITY_CATEGORY_COVERAGE_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="quality reporting must detect reverse event category mapping conflicts",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor='"HAVING count(DISTINCT position_id) > 1) SELECT count(*) FROM conflicts"',
        replacement='"HAVING false) SELECT count(*) FROM conflicts"  # DELIBERATE BREAK',
        command=QUALITY_CATEGORY_COVERAGE_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="quality reporting must detect shot-end coordinate violations",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor='"end_location_x < 0 OR end_location_x > 120 OR "',
        replacement='"false OR "  # DELIBERATE BREAK',
        command=QUALITY_INTEGRITY_DEFECT_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="quality reporting must detect embedded freeze-frame coordinate violations",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor='"f.location_x < 0 OR f.location_x > 120 OR "',
        replacement='"false OR "  # DELIBERATE BREAK',
        command=QUALITY_INTEGRITY_DEFECT_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="quality reporting must expose unmatched same-match-team event actors",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor='"AND lm.player_id IS NULL",',
        replacement='"AND false",  # DELIBERATE BREAK',
        command=QUALITY_CATEGORY_COVERAGE_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="future cohort shot fields must have zero missing values",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor='if values["shots_missing_any_future_cohort_field"]:',
        replacement="if False:  # DELIBERATE BREAK",
        command=QUALITY_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="the two-team invariant must include matches with zero participant rows",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor='"LEFT JOIN match_teams mt USING (match_id) GROUP BY sm.match_id "',
        replacement='"JOIN match_teams mt USING (match_id) GROUP BY sm.match_id "',
        command=QUALITY_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="quality reporting must detect invalid event clock values",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor=('"WHERE period NOT BETWEEN 1 AND 5 OR minute < 0 OR second NOT BETWEEN 0 AND 59 "'),
        replacement=(
            '"WHERE period NOT BETWEEN 1 AND 5 OR minute < 0 OR second < 0 " # DELIBERATE BREAK'
        ),
        command=QUALITY_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="quality reporting must detect incomplete shot category id/name pairs",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor='"(outcome_id IS NULL) <> (outcome_name IS NULL) OR "',
        replacement='"false OR "  # DELIBERATE BREAK',
        command=QUALITY_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="quality reporting must detect incomplete event category id/name pairs",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor='"(play_pattern_id IS NULL) <> (play_pattern_name IS NULL) OR "',
        replacement='"false OR "  # DELIBERATE BREAK',
        command=QUALITY_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="quality reporting must preserve lineup-position missingness coverage",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor='"WHERE lp.player_id IS NULL",',
        replacement='"WHERE false",  # DELIBERATE BREAK',
        command=QUALITY_COVERAGE_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="quality reporting must preserve the measured 120.1 event coverage",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor='"WHERE location_x = 120.1",',
        replacement='"WHERE false",  # DELIBERATE BREAK',
        command=QUALITY_X_EXCEPTION_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="quality reporting must preserve generic-event player missingness",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor=(
            '"SELECT count(*) FROM events JOIN scoped_matches USING (match_id) "\n'
            '            "WHERE player_id IS NULL",'
        ),
        replacement='"SELECT 0",  # DELIBERATE BREAK',
        command=QUALITY_COVERAGE_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="quality reporting must preserve generic-event location missingness",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor=(
            '"SELECT count(*) FROM events JOIN scoped_matches USING (match_id) "\n'
            '            "WHERE location_x IS NULL",'
        ),
        replacement='"SELECT 0",  # DELIBERATE BREAK',
        command=QUALITY_COVERAGE_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="quality reporting must preserve generic-event position missingness",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor=(
            '"SELECT count(*) FROM events JOIN scoped_matches USING (match_id) "\n'
            '            "WHERE position_id IS NULL",'
        ),
        replacement='"SELECT 0",  # DELIBERATE BREAK',
        command=QUALITY_COVERAGE_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="quality reporting must preserve generic-event duration missingness",
        path=ROOT / "backend/src/touchline/quality.py",
        anchor=(
            '"SELECT count(*) FROM events JOIN scoped_matches USING (match_id) "\n'
            '            "WHERE duration IS NULL",'
        ),
        replacement='"SELECT 0",  # DELIBERATE BREAK',
        command=QUALITY_COVERAGE_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="quality manifest selection must use relational exact-scope evidence",
        path=ROOT / "backend/src/touchline/quality_cli.py",
        anchor=("            if persisted_scope == wanted and isinstance(attempted_counts, dict):"),
        replacement="            if False:  # DELIBERATE BREAK",
        command=QUALITY_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="/health must not touch the database (liveness)",
        path=ROOT / "backend/src/touchline/main.py",
        anchor=HEALTH_ANCHOR,
        replacement=HEALTH_BROKEN,
        command=OPS_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="db_url must have no default (fail fast on misconfiguration)",
        path=ROOT / "backend/src/touchline/config.py",
        anchor=DB_URL_ANCHOR,
        replacement=DB_URL_BROKEN,
        command=CONFIG_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="migration and ingestion commands must reject Neon pooled endpoints before work",
        path=ROOT / "backend/src/touchline/config.py",
        anchor=(
            '        if normalized.endswith(".neon.tech") and first_label.endswith("-pooler"):'
        ),
        replacement=(
            '        if False and normalized.endswith(".neon.tech") and '
            'first_label.endswith("-pooler"):  # DELIBERATE BREAK'
        ),
        command=DIRECT_DATABASE_COMMAND_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="/ready must report an exception class name only (no secret leak)",
        path=ROOT / "backend/src/touchline/main.py",
        anchor="        return False, type(exc).__name__",
        replacement="        return False, str(exc)  # DELIBERATE BREAK",
        command=OPS_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="the 'no evaluated model' notice must stay while M0 has no model",
        path=FRONTEND / "components/HomeView.tsx",
        anchor='        <p role="note">{PROVISIONAL_NOTICE}</p>',
        replacement="        {/* DELIBERATE BREAK */}",
        command=FRONTEND_TESTS,
        cwd=FRONTEND,
    ),
    Break(
        contract="StatsBomb attribution must stay (licence obligation)",
        path=FRONTEND / "components/HomeView.tsx",
        anchor="          Data provided by StatsBomb.",
        replacement="          DELIBERATE BREAK.",
        command=FRONTEND_TESTS,
        cwd=FRONTEND,
    ),
    Break(
        contract="public endpoints must remain restricted to the WC 2022 publication scope",
        path=ROOT / "backend/src/touchline/public_scope.py",
        anchor=(
            "PUBLIC_SCOPE_PREDICATE = (\n"
            '    "m.competition_id = %(public_competition_id)s AND '
            'm.season_id = %(public_season_id)s"\n'
            ")"
        ),
        replacement='PUBLIC_SCOPE_PREDICATE = "TRUE"  # DELIBERATE BREAK',
        command=PUBLIC_SCOPE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="an identical ingestion rerun must remain a no-op",
        path=ROOT / "backend/src/touchline/ingest/run.py",
        anchor='    conflict_action = sql.SQL("DO NOTHING")',
        replacement=(
            '    conflict_action = sql.SQL("DO UPDATE SET {} = EXCLUDED.{}").format(\n'
            "        sql.Identifier(table.key[0]), sql.Identifier(table.key[0])\n"
            "    )  # DELIBERATE BREAK"
        ),
        command=INGEST_RERUN_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="changed source facts must be rejected before merge",
        path=ROOT / "backend/src/touchline/ingest/run.py",
        anchor="    _raise_if_changed(conn, table, staging, source_count)",
        replacement="    pass  # DELIBERATE BREAK: conflict comparison disabled",
        command=INGEST_CONFLICT_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="a late ingestion failure must roll back earlier table merges",
        path=ROOT / "backend/src/touchline/ingest/run.py",
        anchor='    return {\n        "inserted": inserted,',
        replacement=(
            '    if table.name == "matches":\n'
            "        conn.commit()  # DELIBERATE BREAK\n"
            "    return {\n"
            '        "inserted": inserted,'
        ),
        command=INGEST_ROLLBACK_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="an ordinary handled failure must become a failed manifest",
        path=ROOT / "backend/src/touchline/ingest/run.py",
        anchor=(
            "SET status = 'failed', current_phase = 'failed', phase_updated_at = CURRENT_TIMESTAMP,"
        ),
        replacement=(
            "SET status = 'interrupted', current_phase = 'failed', "
            "phase_updated_at = CURRENT_TIMESTAMP, -- DELIBERATE BREAK"
        ),
        command=INGEST_ROLLBACK_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="the ingestion advisory lock must reject an active concurrent owner",
        path=ROOT / "backend/src/touchline/ingest/run.py",
        anchor=(
            '"SELECT pg_try_advisory_lock("\n'
            '                "hashtext(current_database()), hashtext(current_schema()))"'
        ),
        replacement='"SELECT TRUE  -- DELIBERATE BREAK"',
        command=INGEST_LOCK_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="a later lock owner must recover an abandoned running manifest",
        path=ROOT / "backend/src/touchline/ingest/run.py",
        anchor="        _recover_interrupted(control)",
        replacement="        pass  # DELIBERATE BREAK: abandoned run left running",
        command=INGEST_RECOVERY_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="manifest recovery requires exclusive lifecycle ownership",
        path=ROOT / "backend/src/touchline/ingest/run.py",
        anchor=(
            "def _lock_lifecycle_exclusive(conn: psycopg.Connection) -> None:\n"
            '    """Prove that no active invocation can own a running manifest before '
            'recovery."""\n'
            "    with conn.cursor() as cur:\n"
            "        cur.execute(\n"
            '            "SELECT pg_advisory_lock("\n'
            "            \"hashtextextended(current_database() || ':' || current_schema() \"\n"
            "            \"|| ':ingestion_manifest_lifecycle', 0))\"\n"
            "        )\n"
            "    conn.commit()"
        ),
        replacement=(
            "def _lock_lifecycle_exclusive(conn: psycopg.Connection) -> None:\n"
            "    with conn.cursor() as cur:\n"
            "        cur.execute(\n"
            '            "SELECT pg_advisory_lock_shared("\n'
            "            \"hashtextextended(current_database() || ':' || current_schema() \"\n"
            "            \"|| ':ingestion_manifest_lifecycle', 0))\"\n"
            "        )\n"
            "    conn.commit()  # DELIBERATE BREAK: recovery has only shared ownership"
        ),
        command=INGEST_LIFECYCLE_RACE_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="ingestion scope evidence must not cascade away with its parent manifest",
        path=ROOT / "backend/src/touchline/ingest/migrations/0006_ingestion_runs.sql",
        anchor="    run_id uuid NOT NULL REFERENCES ingestion_runs (run_id),",
        replacement=(
            "    run_id uuid NOT NULL REFERENCES ingestion_runs (run_id) "
            "ON DELETE CASCADE, -- DELIBERATE BREAK"
        ),
        command=INGEST_SCOPE_EVIDENCE_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="an absent shot location must stay NULL, never be coerced to a real coordinate",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor="    if v is None:\n        return None, None",
        replacement="    if v is None:\n        return 0.0, 0.0  # DELIBERATE BREAK",
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="a malformed location must raise, not be silently treated as absent",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor='        raise ParseError(f"expected location to be exactly [x, y], got {v!r}")',
        replacement="        return None, None  # DELIBERATE BREAK",
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="a location must have exactly two elements, not merely at least two",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor=(
            "    if (\n"
            "        not isinstance(v, list)\n"
            "        or len(v) != 2\n"
            "        or not all(not isinstance(x, bool) and "
            "isinstance(x, int | float) for x in v)\n"
            "    ):"
        ),
        replacement=(
            "    if (\n"
            "        not isinstance(v, list)\n"
            "        or len(v) < 2  # DELIBERATE BREAK\n"
            "        or not all(not isinstance(x, bool) and "
            "isinstance(x, int | float) for x in v)\n"
            "    ):"
        ),
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="optional event integer fields must reject coercible wrong types",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor=(
            "def _optional_int(obj: dict[str, Any], key: str, context: str) -> int | None:\n"
            "    value = obj.get(key)\n"
            "    if value is None:\n"
            "        return None\n"
            "    if isinstance(value, bool) or not isinstance(value, int):\n"
            '        raise ParseError(f"expected {context}.{key} to be an integer, got {value!r}")'
        ),
        replacement=(
            "def _optional_int(obj: dict[str, Any], key: str, context: str) -> int | None:\n"
            "    value = obj.get(key)\n"
            "    if value is None:\n"
            "        return None\n"
            "    if False:  # DELIBERATE BREAK\n"
            '        raise ParseError(f"expected {context}.{key} to be an integer, got {value!r}")'
        ),
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="optional event numeric fields must reject coercible strings",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor=(
            "    if isinstance(value, bool) or not isinstance(value, int | float):\n"
            '        raise ParseError(f"expected {context}.{key} to be numeric, got {value!r}")'
        ),
        replacement=(
            "    if False:  # DELIBERATE BREAK\n"
            '        raise ParseError(f"expected {context}.{key} to be numeric, got {value!r}")'
        ),
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="optional event and shot booleans must reject truthy non-booleans",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor=(
            "    if not isinstance(value, bool):\n"
            '        raise ParseError(f"expected {context}.{key} to be boolean, got {value!r}")'
        ),
        replacement=(
            "    if False:  # DELIBERATE BREAK\n"
            '        raise ParseError(f"expected {context}.{key} to be boolean, got {value!r}")'
        ),
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="optional event string fields must reject non-string values",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor=(
            "def _optional_str(obj: dict[str, Any], key: str, context: str) -> str | None:\n"
            "    value = obj.get(key)\n"
            "    if value is None:\n"
            "        return None\n"
            "    if not isinstance(value, str):\n"
            '        raise ParseError(f"expected {context}.{key} to be a string, got {value!r}")'
        ),
        replacement=(
            "def _optional_str(obj: dict[str, Any], key: str, context: str) -> str | None:\n"
            "    value = obj.get(key)\n"
            "    if value is None:\n"
            "        return None\n"
            "    if False:  # DELIBERATE BREAK\n"
            '        raise ParseError(f"expected {context}.{key} to be a string, got {value!r}")'
        ),
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="required lineup integer fields must reject coercible values",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor=(
            "def _required_int(obj: Any, key: str, context: str) -> int:\n"
            "    value = _require(obj, key, context)\n"
            "    if isinstance(value, bool) or not isinstance(value, int):\n"
            '        raise ParseError(f"expected {context}.{key} to be an integer, got {value!r}")'
        ),
        replacement=(
            "def _required_int(obj: Any, key: str, context: str) -> int:\n"
            "    value = _require(obj, key, context)\n"
            "    if False:  # DELIBERATE BREAK\n"
            '        raise ParseError(f"expected {context}.{key} to be an integer, got {value!r}")'
        ),
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="required lineup string fields must reject coercible values",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor=(
            "def _required_str(obj: Any, key: str, context: str) -> str:\n"
            "    value = _require(obj, key, context)\n"
            "    if not isinstance(value, str):\n"
            '        raise ParseError(f"expected {context}.{key} to be a string, got {value!r}")'
        ),
        replacement=(
            "def _required_str(obj: Any, key: str, context: str) -> str:\n"
            "    value = _require(obj, key, context)\n"
            "    if False:  # DELIBERATE BREAK\n"
            '        raise ParseError(f"expected {context}.{key} to be a string, got {value!r}")'
        ),
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="lineup members must remain a list container",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor=(
            "        if not isinstance(raw_lineup, list):\n"
            '            raise ParseError(f"expected {team_context}.lineup to be a list, '
            'got {raw_lineup!r}")'
        ),
        replacement=(
            "        if not isinstance(raw_lineup, list):\n"
            "            raw_lineup = []  # DELIBERATE BREAK"
        ),
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="lineup positions must remain a list container",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor=(
            "            if not isinstance(positions, list):\n"
            '                raise ParseError("expected lineup member.positions to be a list")'
        ),
        replacement=(
            "            if not isinstance(positions, list):\n"
            "                positions = []  # DELIBERATE BREAK"
        ),
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="lineup cards must remain a list container",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor=(
            "            if not isinstance(cards, list):\n"
            '                raise ParseError("expected lineup member.cards to be a list")'
        ),
        replacement=(
            "            if not isinstance(cards, list):\n"
            "                cards = []  # DELIBERATE BREAK"
        ),
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="config tests must be hermetic against the real environment",
        path=ROOT / "backend/tests/test_config.py",
        anchor="        monkeypatch.delenv(name, raising=False)",
        replacement="        pass  # DELIBERATE BREAK",
        command=CONFIG_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="the loader must not commit - the caller owns the transaction",
        path=ROOT / "backend/src/touchline/ingest/load.py",
        anchor="    return LoadCounts(**counts)",
        replacement="    conn.commit()  # DELIBERATE BREAK\n    return LoadCounts(**counts)",
        command=LOAD_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="the base rate must exclude penalties",
        path=ROOT / "backend/src/touchline/baseline.py",
        anchor="    \"AND s.shot_type_name <> 'Penalty' \"",
        replacement='    "AND true "  # DELIBERATE BREAK',
        command=BASELINE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="fetch_shots must make its own transaction read-only",
        path=ROOT / "backend/src/touchline/shots.py",
        anchor='cur.execute("SET TRANSACTION READ ONLY")',
        replacement="pass  # DELIBERATE BREAK",
        command=SHOTS_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="a map showing fewer shots than the API reports must disclose the shortfall",
        path=FRONTEND / "components/HomeView.tsx",
        anchor="            {missing > 0 && (",
        replacement="            {false && (  /* DELIBERATE BREAK */",
        command=FRONTEND_TESTS,
        cwd=FRONTEND,
    ),
    Break(
        contract="an empty database must raise, not report a conversion rate of zero",
        path=ROOT / "backend/src/touchline/baseline.py",
        anchor="    if shots == 0:\n        raise NoDataError(",
        replacement="    if False:  # DELIBERATE BREAK\n        raise NoDataError(",
        command=BASELINE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="migrations must be applied in their declared order",
        path=ROOT / "backend/src/touchline/ingest/migrate.py",
        anchor="    migrations = read_migrations()",
        replacement=("    migrations = tuple(reversed(read_migrations()))  # DELIBERATE BREAK"),
        command=MIGRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="applied migration checksum drift must be rejected",
        path=ROOT / "backend/src/touchline/ingest/migrate.py",
        anchor="            if checksum != by_version[version].checksum:",
        replacement="            if False:  # DELIBERATE BREAK",
        command=MIGRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="applied migration history must be an exact ordered prefix",
        path=ROOT / "backend/src/touchline/ingest/migrate.py",
        anchor="        if applied_versions != packaged_versions[: len(applied_versions)]:",
        replacement="        if False:  # DELIBERATE BREAK",
        command=MIGRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="an unversioned M0 schema must match its known physical signature",
        path=ROOT / "backend/src/touchline/ingest/migrate.py",
        anchor="            _validate_unversioned_m0_schema(conn)",
        replacement="            pass  # DELIBERATE BREAK",
        command=MIGRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="the destructive rebuild must use the ordered migrations",
        path=ROOT / "backend/src/touchline/ingest/load.py",
        anchor="    apply_migrations(conn)",
        replacement="    return  # DELIBERATE BREAK",
        command=LOAD_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="a shot must reference an existing event",
        path=ROOT / "backend/src/touchline/ingest/migrations/0005_event_and_lineup_constraints.sql",
        anchor=(
            "    ADD CONSTRAINT shots_event_fk FOREIGN KEY (event_id, event_type_name)\n"
            "        REFERENCES events (event_id, event_type_name),"
        ),
        replacement=(
            "    ADD CONSTRAINT shots_event_fk CHECK (event_id IS NOT NULL), -- DELIBERATE BREAK"
        ),
        command=MIGRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="an event must reference an existing match",
        path=ROOT / "backend/src/touchline/ingest/migrations/0005_event_and_lineup_constraints.sql",
        anchor=(
            "    ADD CONSTRAINT events_match_fk FOREIGN KEY (match_id) "
            "REFERENCES matches (match_id),"
        ),
        replacement=(
            "    ADD CONSTRAINT events_match_fk CHECK (match_id > 0), -- DELIBERATE BREAK"
        ),
        command=MIGRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="event x coordinates must retain the measured 120.1 source boundary",
        path=ROOT / "backend/src/touchline/ingest/migrations/0007_measured_event_x_boundary.sql",
        anchor=(
            "    ADD CONSTRAINT events_location_x_measured_source_bounds\n"
            "        CHECK (location_x IS NULL OR location_x BETWEEN 0.0 AND 120.1);"
        ),
        replacement=(
            "    ADD CONSTRAINT events_location_x_measured_source_bounds\n"
            "        CHECK (location_x IS NULL OR location_x >= 0.0); -- DELIBERATE BREAK"
        ),
        command=MIGRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="event y coordinates must remain within the StatsBomb pitch",
        path=ROOT / "backend/src/touchline/ingest/migrations/0005_event_and_lineup_constraints.sql",
        anchor=(
            "    ADD CONSTRAINT events_location_y_bounds "
            "CHECK (location_y IS NULL OR location_y BETWEEN 0.0 AND 80.0),"
        ),
        replacement=(
            "    ADD CONSTRAINT events_location_y_bounds "
            "CHECK (location_y IS NULL OR location_y BETWEEN -1000.0 AND 1000.0), "
            "-- DELIBERATE BREAK"
        ),
        command=MIGRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="provider xG must be removed recursively before JSONB persistence",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor=(
            '        return {k: _strip_xg(v) for k, v in value.items() if k != "statsbomb_xg"}'
        ),
        replacement=(
            "        return {k: _strip_xg(v) for k, v in value.items()} # DELIBERATE BREAK"
        ),
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="lineup positions must preserve one-based source order",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor="            for i, p in enumerate(positions, start=1):",
        replacement=("            for i, p in enumerate(positions, start=0):  # DELIBERATE BREAK"),
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="lineup cards must preserve one-based source order",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor="            for i, c in enumerate(cards, start=1):",
        replacement=("            for i, c in enumerate(cards, start=0):  # DELIBERATE BREAK"),
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="full fixture ingestion must load every generic event",
        path=ROOT / "backend/src/touchline/ingest/load.py",
        anchor="        for r in events\n    ]",
        replacement="        for r in events if r.type_name == 'Shot'  # DELIBERATE BREAK\n    ]",
        command=LOAD_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="event indexes must be unique within a match",
        path=ROOT / "backend/src/touchline/ingest/migrations/0005_event_and_lineup_constraints.sql",
        anchor="    ADD CONSTRAINT events_match_index_unique UNIQUE (match_id, event_index),",
        replacement="    -- DELIBERATE BREAK: event index uniqueness removed",
        command=MIGRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="directed event relations must reference a source event in the same match",
        path=ROOT / "backend/src/touchline/ingest/migrations/0005_event_and_lineup_constraints.sql",
        anchor=(
            "    ADD CONSTRAINT event_relations_source_event_fk "
            "FOREIGN KEY (match_id, source_event_id)\n"
            "        REFERENCES events (match_id, event_id),"
        ),
        replacement="    -- DELIBERATE BREAK: source relation foreign key removed",
        command=MIGRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="JSONB must reject provider xG even if parser protection regresses",
        path=ROOT / "backend/src/touchline/ingest/migrations/0005_event_and_lineup_constraints.sql",
        anchor=(
            "    ADD CONSTRAINT events_no_provider_xg\n"
            "        CHECK (type_data IS NULL OR NOT "
            "jsonb_path_exists(type_data, '$.**.statsbomb_xg'));"
        ),
        replacement=("    ADD CONSTRAINT events_no_provider_xg CHECK (true); -- DELIBERATE BREAK"),
        command=MIGRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="shot details may attach only to events whose type is Shot",
        path=ROOT / "backend/src/touchline/ingest/migrations/0005_event_and_lineup_constraints.sql",
        anchor=(
            "    ADD CONSTRAINT shots_event_fk FOREIGN KEY (event_id, event_type_name)\n"
            "        REFERENCES events (event_id, event_type_name),"
        ),
        replacement=(
            "    ADD CONSTRAINT shots_event_fk FOREIGN KEY (event_id) "
            "REFERENCES events (event_id), -- DELIBERATE BREAK"
        ),
        command=MIGRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="shot freeze-frame actors must reference a typed shot detail",
        path=ROOT / "backend/src/touchline/ingest/migrations/0005_event_and_lineup_constraints.sql",
        anchor=(
            "    ADD CONSTRAINT shot_freeze_frame_players_shot_fk FOREIGN KEY (event_id)\n"
            "        REFERENCES shots (event_id),"
        ),
        replacement=(
            "    ADD CONSTRAINT shot_freeze_frame_players_shot_fk FOREIGN KEY (event_id)\n"
            "        REFERENCES events (event_id), -- DELIBERATE BREAK"
        ),
        command=MIGRATION_TESTS,
        cwd=ROOT,
    ),
    # The three below protect the repair for the deployment outage in which the served build's
    # queries had moved ahead of the database's schema. Each mutation restores one part of the
    # behaviour that let a completely unservable deployment report itself healthy.
    Break(
        contract="readiness must detect a reachable database whose schema is behind the build",
        path=ROOT / "backend/src/touchline/schema_state.py",
        anchor="    return tuple(table for table in REQUIRED_TABLES if table not in present)\n",
        replacement="    return ()  # DELIBERATE BREAK\n",
        command=SCHEMA_DRIFT_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="a schema-drift 503 must explain the cause, not echo the driver's symbol",
        path=ROOT / "backend/src/touchline/schema_state.py",
        anchor=(
            "SCHEMA_NOT_MIGRATED_DETAIL = (\n"
            '    "database schema is behind this build; the ordered migrations have not been '
            'applied to it"\n)'
        ),
        replacement='SCHEMA_NOT_MIGRATED_DETAIL = "UndefinedTable"  # DELIBERATE BREAK',
        command=SCHEMA_DRIFT_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="a production frontend must not silently fall back to a localhost API",
        path=FRONTEND / "lib/api.ts",
        anchor="    throw new ApiBaseNotConfiguredError();\n",
        replacement="    return LOCAL_API_BASE; // DELIBERATE BREAK\n",
        command=FRONTEND_TESTS,
        cwd=FRONTEND,
    ),
]


def _tests_fail(command: str, cwd: Path) -> bool:
    """Run a test command and report whether it failed, which is the desired outcome here."""
    # shell=True is safe here: every command is a fixed literal defined above in this file,
    # with no interpolation of external input.
    result = subprocess.run(
        command,
        cwd=cwd,
        shell=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode != 0


def check(defect: Break) -> bool:
    """Apply one break, run its tests, restore the file. True when the break was caught."""
    original = defect.path.read_text(encoding="utf-8")
    occurrences = original.count(defect.anchor)
    if occurrences != 1:
        print(
            f"[MISSED] mutation anchor matched {occurrences} times; expected exactly once: "
            f"{defect.contract}"
        )
        return False

    mutated = original.replace(defect.anchor, defect.replacement, 1)
    if defect.path.suffix == ".py":
        try:
            compile(mutated, str(defect.path), "exec")
        except SyntaxError as exc:
            print(f"[MISSED] mutation produced invalid Python: {defect.contract}: {exc.msg}")
            return False

    defect.path.write_text(mutated, encoding="utf-8")
    try:
        caught = _tests_fail(defect.command, defect.cwd)
    finally:
        defect.path.write_text(original, encoding="utf-8")

    print(f"[{'CAUGHT' if caught else 'MISSED'}] {defect.contract}")
    return caught


def main() -> int:
    results = [check(defect) for defect in BREAKS]
    caught = results.count(True)
    missed = results.count(False)
    print(f"\nMutation totals: {caught} CAUGHT, {missed} MISSED, 0 SKIP")
    if all(results):
        print(f"\nAll {len(results)} contracts are genuinely protected. Files restored.")
        return 0
    print(f"\n{missed} of {len(results)} breaks went unnoticed. Files restored.")
    print("A test that does not fail here is not protecting anything.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
