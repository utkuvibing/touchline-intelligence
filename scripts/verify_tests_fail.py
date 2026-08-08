"""Verify that the test suite actually protects what it claims to.

A green suite proves the tests pass, not that they would fail if the behaviour broke. This script
introduces one deliberate break per protected contract, runs the relevant tests, asserts they fail,
and restores the file.

Run with a clean working tree, **and with both database variables set**:

    TOUCHLINE_DB_URL=... TOUCHLINE_FULL_COHORT_DB_URL=... uv run python scripts/verify_tests_fail.py

Both are required, and the script refuses to start without them. Integration and full-cohort tests
skip when their variable is missing; a skipped test suite exits zero, which this harness would read
as "the mutation was not noticed". A run without the variables once reported 71 CAUGHT and 98
MISSED where the real figure was 169 CAUGHT — an environment gap masquerading as 98 unprotected
contracts. Refusing up front is cheaper than the investigation that mistake costs.

It has already earned its place three times. It found that the /health liveness test passed even
when /health was made to call the database (the failure was invisible from the response body), that
the /ready secret-leak test passed for the wrong reason because its substring blocklist missed the
actual driver error, and that the read-only test configured a separate transaction instead of
observing the production query's transaction. All three tests were rewritten.
"""

from __future__ import annotations

import os
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

UNKNOWN_HOST_ANCHOR = "    if not isinstance(host, str) or not host:\n        return False\n"
UNKNOWN_HOST_BROKEN = (
    "    if not isinstance(host, str) or not host:\n        return True  # DELIBERATE BREAK\n"
)

WRITE_GUARD_ANCHOR = (
    "    if is_local_write_target(db_url):\n        return\n\n    target = write_target(db_url)"
)
WRITE_GUARD_BROKEN = (
    "    if True:  # DELIBERATE BREAK\n        return\n\n    target = write_target(db_url)"
)

OVERRIDE_ANCHOR = '    if os.environ.get(REMOTE_WRITE_OVERRIDE_VAR, "").strip() == target:\n'
OVERRIDE_BROKEN = (
    '    if os.environ.get(REMOTE_WRITE_OVERRIDE_VAR, "").strip():  # DELIBERATE BREAK\n'
)

SANITIZED_TARGET_ANCHOR = (
    '    database = (db_url.path or "").lstrip("/")\n'
    '    return f"{label}/{database}" if database else label\n'
)
SANITIZED_TARGET_BROKEN = "    return str(db_url)  # DELIBERATE BREAK\n"

OPS_TESTS = "uv run pytest backend/tests/test_ops_endpoints.py -q"
CONFIG_TESTS = "uv run pytest backend/tests/test_config.py -q"
DIRECT_DATABASE_COMMAND_TESTS = "uv run pytest backend/tests/test_ingest_command_policy.py -q"
WRITE_TARGET_TESTS = "uv run pytest backend/tests/test_write_target_policy.py -q"
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
# WP2.2 Slice A geometry. The unit tests need no database, so these mutations are the only ones in
# this script that are guaranteed to run everywhere rather than reporting MISSED without a DSN.
WP22_TESTS = "uv run pytest backend/tests/test_wp2_2_geometry.py -q"
WP21_PROVIDER_XG_TEST = (
    "uv run pytest backend/tests/test_wp2_1_cohort_integration.py::"
    "test_the_cohort_sql_never_exposes_provider_xg -q"
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
# WP2.2 Slice B coverage. Like the Slice A full-cohort module, these need the ingested
# four-tournament database rather than merely a reachable PostgreSQL, so they report MISSED unless
# TOUCHLINE_FULL_COHORT_DB_URL is exported.
WP22_COVERAGE_TESTS = "uv run pytest backend/tests/test_wp2_2_coverage_integration.py -q"
WP22_PARTITION_TEST = (
    "uv run pytest backend/tests/test_wp2_2_coverage_integration.py::"
    "test_per_tournament_columns_partition_each_level -q"
)
WP22_ENCODING_FALSE_TEST = (
    "uv run pytest backend/tests/test_wp2_2_coverage_integration.py::"
    "test_no_candidate_boolean_ever_records_an_explicit_false -q"
)
WP22_ENCODING_COUNTS_TEST = (
    "uv run pytest backend/tests/test_wp2_2_coverage_integration.py::"
    "test_annotation_encoding_matches_the_measured_counts -q"
)
WP22_SPARSE_LEVEL_TEST = (
    "uv run pytest backend/tests/test_wp2_2_coverage_integration.py::"
    "test_only_the_corner_shot_type_is_missing_from_a_whole_tournament -q"
)
# WP2.3 split assignment. The unit tests need no database, so most of these mutations are the
# second group in this script (after WP2.2 geometry) that are guaranteed to run everywhere.
# The two SQL mutations need the fixture integration module, which requires TOUCHLINE_DB_URL.
WP23_UNIT_TESTS = "uv run pytest backend/tests/test_wp2_3_splits.py -q"
WP23_INTEGRATION_TESTS = "uv run pytest backend/tests/test_wp2_3_split_integration.py -q"
WP16_FIXTURE_MANIFEST_TESTS = "uv run pytest backend/tests/test_wp1_6_fixture_manifest.py -q"
# WP2.4 baselines and regularized logistic regression. The model/preprocessing/metrics mutations
# are plain unit tests that run everywhere; the loader-hash mutation rides on the dataset unit
# module (also runs everywhere), and the loader-filter mutation needs a database for the
# calibration/holdout rows, so it reports MISSED without TOUCHLINE_DB_URL (honest: unrun).
WP24_METRICS_TESTS = "uv run pytest backend/tests/test_wp2_4_metrics.py -q"
WP24_PREPROCESSING_TESTS = "uv run pytest backend/tests/test_wp2_4_preprocessing.py -q"
WP24_TRAIN_MODELING_TESTS = "uv run pytest backend/tests/test_wp2_4_train_modeling.py -q"
WP24_DATASET_CRLF_TEST = (
    "uv run pytest backend/tests/test_wp2_4_dataset.py::"
    "test_crlf_checkout_fails_loudly_never_normalized -q"
)
WP24_DATASET_HASH_TESTS = (
    "uv run pytest backend/tests/test_wp2_4_dataset.py::"
    "test_hash_mismatch_fails_for_assignments_and_cohort_sql -q"
)
WP24_LOADER_FILTER_TESTS = (
    "uv run pytest backend/tests/test_wp2_4_dataset.py::"
    "test_loader_rejects_a_non_development_row_that_reaches_the_client "
    "backend/tests/test_wp2_4_dataset_integration.py -q"
)
WP24_EXPERIMENT_CONSISTENCY_TESTS = (
    "uv run pytest backend/tests/test_wp2_4_experiment_consistency.py::"
    "test_write_experiment_records_the_shipped_candidate_only -q"
)
WP24_NOTES_PUBLICATION_TESTS = (
    "uv run pytest backend/tests/test_wp2_4_experiment_consistency.py::"
    "test_generated_notes_are_portable_and_stay_inside_the_publication -q"
)
WP24_ARTIFACT_TESTS = "uv run pytest backend/tests/test_wp2_4_artifact.py -q"
#: WP2.5 gave the column-contract validator a second caller (the boosting bundle). A break in the
#: shared validator must be caught by *both* families' tests, or the check could be weakened for
#: whichever family happens not to cover it.
ARTIFACT_CONTRACT_TESTS = (
    "uv run pytest backend/tests/test_wp2_4_artifact.py backend/tests/test_wp2_5_artifact.py -q"
)
WP24_PROVENANCE_TESTS = "uv run pytest backend/tests/test_wp2_4_provenance.py -q"
WP25_BOOSTING_TESTS = "uv run pytest backend/tests/test_wp2_5_boosting.py -q"
WP25_TRAIN_MODELING_TESTS = "uv run pytest backend/tests/test_wp2_5_train_modeling.py -q"
WP25_PRE_REGISTRATION_TESTS = "uv run pytest backend/tests/test_wp2_5_pre_registration.py -q"
WP25_PROCESS_DETERMINISM_TESTS = "uv run pytest backend/tests/test_wp2_5_process_determinism.py -q"
WP25_ARTIFACT_INTEGRITY_TESTS = "uv run pytest backend/tests/test_wp2_5_artifact_integrity.py -q"
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
    Break(
        contract="the WP2.1 cohort projection must never select provider xG",
        path=ROOT / "backend/sql/wp2_1/01_model_shot_cohort.sql",
        anchor="    s.shot_type_id,\n",
        replacement="    s.shot_type_id, NULL AS statsbomb_xg, -- DELIBERATE BREAK\n",
        command=WP21_PROVIDER_XG_TEST,
        cwd=ROOT,
    ),
    # WP2.2 Slice B coverage evidence. The population anchors come first: every reading in the
    # coverage report is only meaningful if it was measured on exactly WP2.1's 5,606 rows, and
    # both Slice B queries duplicate that predicate set rather than importing it.
    Break(
        contract="WP2.2 categorical support must be measured on the non-penalty cohort",
        path=ROOT / "backend/sql/wp2_2/03_categorical_support.sql",
        anchor="      AND s.shot_type_name <> 'Penalty'\n",
        replacement="      AND true -- DELIBERATE BREAK\n",
        command=WP22_COVERAGE_TESTS,
        cwd=ROOT,
    ),
    # The obvious companion mutation -- dropping `e.period <> 5` -- is deliberately absent. All 142
    # period-five shots in this scope are Penalty shots, so on real data that predicate is fully
    # redundant with the one above and its removal changes no count here. WP2.1 proves the two
    # exclusions are independent with a seeded period-five non-penalty shot; a mutation that cannot
    # fail would only have added a green tick that means nothing.
    Break(
        contract="WP2.2 annotation audit must be measured on the non-penalty cohort",
        path=ROOT / "backend/sql/wp2_2/04_annotation_encoding_audit.sql",
        anchor="      AND s.shot_type_name <> 'Penalty'\n",
        replacement="      AND true -- DELIBERATE BREAK\n",
        command=WP22_COVERAGE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.2 per-tournament columns must partition the cohort, not overlap",
        path=ROOT / "backend/sql/wp2_2/03_categorical_support.sql",
        anchor=(
            "    count(*) FILTER (WHERE competition_id = 55 AND season_id = 282)     AS euro_2024"
        ),
        replacement=(
            "    count(*) FILTER (WHERE competition_id = 55) AS euro_2024 -- DELIBERATE BREAK"
        ),
        command=WP22_PARTITION_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.2 must report a level that is missing from a whole tournament",
        path=ROOT / "backend/sql/wp2_2/03_categorical_support.sql",
        anchor=(
            "    count(*) FILTER (WHERE competition_id = 43 AND season_id = 3)       AS wc_2018,"
        ),
        replacement=(
            "    count(*) FILTER (WHERE competition_id = 43 AND season_id = 3 AND false) "
            "AS wc_2018, -- DELIBERATE BREAK"
        ),
        command=WP22_SPARSE_LEVEL_TEST,
        cwd=ROOT,
    ),
    # The absent-versus-false contract. If this column stopped distinguishing a recorded FALSE from
    # an absent annotation, the audit would report zero explicit falses for the wrong reason and
    # the WP2.1 question it closes would silently reopen.
    Break(
        contract="WP2.2 annotation audit must count a recorded false as a false",
        path=ROOT / "backend/sql/wp2_2/04_annotation_encoding_audit.sql",
        anchor=(
            "    count(*) FILTER (WHERE flag IS FALSE)"
            "                               AS recorded_false,"
        ),
        replacement=(
            "    count(*) FILTER (WHERE flag IS NOT TRUE) AS recorded_false, -- DELIBERATE BREAK"
        ),
        command=WP22_ENCODING_FALSE_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.2 annotation audit must count only a recorded true as a true",
        path=ROOT / "backend/sql/wp2_2/04_annotation_encoding_audit.sql",
        anchor=(
            "    count(*) FILTER (WHERE flag IS TRUE)"
            "                                AS recorded_true,"
        ),
        replacement=(
            "    count(*) FILTER (WHERE flag IS NOT FALSE) AS recorded_true, -- DELIBERATE BREAK"
        ),
        command=WP22_ENCODING_COUNTS_TEST,
        cwd=ROOT,
    ),
    # WP2.3 split assignment. Each break is one of the ways the locked split could look right and
    # be wrong: a scope constant that silently moves a tournament, a fold rule that no longer
    # round-robins, a fold sort that drops the match_id tie-break, a NULL-date guard that stops
    # raising, and either SQL query admitting a penalty into the population it must exclude.
    Break(
        contract="WP2.3 holdout scope must remain Euro 2024 (55,282)",
        path=ROOT / "backend/src/touchline/modeling/splits.py",
        anchor="HOLDOUT_SCOPE = (55, 282)",
        replacement="HOLDOUT_SCOPE = (55, 43)  # DELIBERATE BREAK",
        command=WP23_UNIT_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.3 calibration scope must remain World Cup 2022 (43,106)",
        path=ROOT / "backend/src/touchline/modeling/splits.py",
        anchor="CALIBRATION_SCOPE = (43, 106)",
        replacement="CALIBRATION_SCOPE = (43, 3)  # DELIBERATE BREAK",
        command=WP23_UNIT_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.3 folds must round-robin with index modulo the locked fold count",
        path=ROOT / "backend/src/touchline/modeling/splits.py",
        anchor=(
            "match_id: index % N_FOLDS for index, (match_id, _match_date) in enumerate(development)"
        ),
        replacement=(
            "match_id: (index + 1) % N_FOLDS for index, (match_id, _match_date) "
            "in enumerate(development)  # DELIBERATE BREAK"
        ),
        command=WP23_UNIT_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.3 fold sort must tie-break equal dates by match_id",
        path=ROOT / "backend/src/touchline/modeling/splits.py",
        anchor="    development.sort(key=lambda pair: (pair[1], pair[0]))",
        replacement="    development.sort(key=lambda pair: (pair[1],))  # DELIBERATE BREAK",
        command=WP23_UNIT_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.3 assignment must fail explicitly on a missing match date",
        path=ROOT / "backend/src/touchline/modeling/splits.py",
        anchor="    if record.match_date is None:",
        replacement="    if False:  # DELIBERATE BREAK",
        command=WP23_UNIT_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.3 match population must exclude Penalty shot types",
        path=ROOT / "backend/sql/wp2_3/01_split_match_population.sql",
        anchor="      AND s.shot_type_name <> 'Penalty'\n",
        replacement="      AND true -- DELIBERATE BREAK\n",
        command=WP23_INTEGRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.3 shot membership must exclude Penalty shot types",
        path=ROOT / "backend/sql/wp2_3/02_split_shot_membership.sql",
        anchor="  AND s.shot_type_name <> 'Penalty'\n",
        replacement="  AND true -- DELIBERATE BREAK\n",
        command=WP23_INTEGRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.3 assignment CSV must stay byte-pinned against silent edits",
        path=ROOT / "data/model/wp2_3_match_assignments.csv",
        anchor="match_id,competition_id,season_id,match_date,split,fold\n",
        replacement=(  # DELIBERATE BREAK
            "match_id,competition_id,season_id,match_date,split,foldX\n"
        ),
        command=(
            "uv run pytest backend/tests/test_wp2_3_split_full_cohort.py::"
            "test_committed_assignment_csv_is_byte_pinned -q"
        ),
        cwd=ROOT,
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
        # The anchor went stale when this function started returning a DatabaseState, and a break
        # whose anchor matches nothing verifies nothing. Re-pointed at the line that actually
        # decides what an unauthenticated /ready is allowed to disclose.
        anchor="        return DatabaseState(reachable=False, schema_current=False, "
        "detail=type(exc).__name__)",
        replacement="        return DatabaseState(reachable=False, schema_current=False, "
        "detail=str(exc))  # DELIBERATE BREAK",
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
    # WP2.2 Slice A. Each break is one of the ways the geometry could look right and be wrong:
    # the quadrant collapse the two-post form exists to prevent, a wrong constant, a distance that
    # ignores one axis, and each of the three guards that keep an undefined input from returning a
    # plausible number.
    Break(
        contract="the visible goal angle must recover the quadrant, not collapse it to a ratio",
        path=ROOT / "backend/src/touchline/features/geometry.py",
        anchor="    return math.atan2(cross, dot)\n",
        replacement="    return math.atan(cross / dot)  # DELIBERATE BREAK\n",
        command=WP22_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="goalpost coordinates must match the StatsBomb specification",
        path=ROOT / "backend/src/touchline/features/geometry.py",
        anchor="LEFT_POST_Y = 36.0\n",
        replacement="LEFT_POST_Y = 35.0  # DELIBERATE BREAK\n",
        command=WP22_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="distance to goal must use both axes",
        path=ROOT / "backend/src/touchline/features/geometry.py",
        anchor="    return math.hypot(GOAL_LINE_X - effective_x, y - GOAL_CENTRE_Y)\n",
        replacement="    return abs(GOAL_LINE_X - effective_x)  # DELIBERATE BREAK\n",
        command=WP22_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="a shot exactly on a goalpost must raise, not report a visible angle of zero",
        path=ROOT / "backend/src/touchline/features/geometry.py",
        anchor="    if effective_x == GOAL_LINE_X and y in (LEFT_POST_Y, RIGHT_POST_Y):\n",
        replacement="    if False:  # DELIBERATE BREAK\n",
        command=WP22_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="the source-coordinate tolerance adjustment must stay bounded, never clamp",
        path=ROOT / "backend/src/touchline/features/geometry.py",
        anchor="    elif x <= MEASURED_MAX_SOURCE_X + COORDINATE_TOLERANCE:\n",
        replacement="    elif True:  # DELIBERATE BREAK\n",
        command=WP22_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="a location off the pitch must raise rather than produce a feature",
        path=ROOT / "backend/src/touchline/features/geometry.py",
        anchor="    if not 0.0 <= y <= PITCH_WIDTH:\n",
        replacement="    if False:  # DELIBERATE BREAK\n",
        command=WP22_TESTS,
        cwd=ROOT,
    ),
    # The write-target guard. Each break is one of the plausible ways it could be weakened into
    # something that still passes a casual reading: an open-by-default classification, a generic
    # truthy override, trusting the self-declared environment label, and leaking the DSN into the
    # refusal it prints.
    Break(
        contract="an unclassifiable write target must be refused, not assumed local",
        path=ROOT / "backend/src/touchline/config.py",
        anchor=UNKNOWN_HOST_ANCHOR,
        replacement=UNKNOWN_HOST_BROKEN,
        command=WRITE_TARGET_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="a non-local write target must be refused without the deliberate override",
        path=ROOT / "backend/src/touchline/config.py",
        anchor=WRITE_GUARD_ANCHOR,
        replacement=WRITE_GUARD_BROKEN,
        command=WRITE_TARGET_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="a generic truthy override must not unlock a remote write",
        path=ROOT / "backend/src/touchline/config.py",
        anchor=OVERRIDE_ANCHOR,
        replacement=OVERRIDE_BROKEN,
        command=WRITE_TARGET_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="the refusal must name the target without printing the DSN",
        path=ROOT / "backend/src/touchline/config.py",
        anchor=SANITIZED_TARGET_ANCHOR,
        replacement=SANITIZED_TARGET_BROKEN,
        command=WRITE_TARGET_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="ingestion must consult the write-target guard before any work",
        path=ROOT / "backend/src/touchline/ingest/cli.py",
        anchor='        require_local_write_target(settings.db_url, command="ingest")\n',
        replacement="        pass  # DELIBERATE BREAK\n",
        command=WRITE_TARGET_TESTS,
        cwd=ROOT,
    ),
    # WP2.4 baselines and regularized logistic regression. Eight contracts, each the kind of thing
    # that looks right and is wrong: a constant trained on its own validation rows, a reliability
    # bin count that drifts from five, an unseen level that starts raising, a loader that lets
    # calibration/holdout labels reach the client, a scaler fitted on validation rows, either
    # pinned-artifact hash silently dropped, and a loader that silently tolerates a CRLF checkout.
    Break(
        contract="WP2.4 constant baseline must use the training-fold goal rate only",
        path=ROOT / "backend/src/touchline/modeling/protocol.py",
        anchor="        baseline = ConstantBaseline.fit([r.y for r in train])\n",
        replacement=(
            "        baseline = ConstantBaseline.fit([r.y for r in rows])  # DELIBERATE BREAK\n"
        ),
        command=WP24_TRAIN_MODELING_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.4 reliability bin count is locked at five (ADR 0004)",
        path=ROOT / "backend/src/touchline/modeling/metrics.py",
        anchor="    if n_bins != N_RELIABILITY_BINS:\n",
        replacement="    if False:  # DELIBERATE BREAK\n",
        command=WP24_METRICS_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.4 unseen categorical levels must encode as the reference, never raise",
        path=ROOT / "backend/src/touchline/modeling/preprocessing.py",
        anchor="        flags[existing.index(RARE_LEVEL)] = 1\n    return flags\n",
        replacement=(
            "        flags[existing.index(RARE_LEVEL)] = 1\n"
            '    raise ValueError("unseen level -- DELIBERATE BREAK")\n'
        ),
        command=WP24_PREPROCESSING_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.4 loader must filter to development match ids server-side",
        path=ROOT / "backend/src/touchline/modeling/dataset.py",
        anchor='    sql = f"SELECT {LOAD_COLUMNS} FROM ({body}) AS cohort '
        'WHERE match_id = ANY(%s) ORDER BY shot_id"\n',
        replacement=(
            '    sql = f"SELECT {LOAD_COLUMNS} FROM ({body}) AS cohort WHERE TRUE '
            'ORDER BY shot_id"  # DELIBERATE BREAK\n'
        ),
        command=WP24_LOADER_FILTER_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.4 fold scaler must be fitted on training rows only",
        path=ROOT / "backend/src/touchline/modeling/protocol.py",
        anchor="        scaler = fit_scaler(train)\n",
        replacement="        scaler = fit_scaler(rows)  # DELIBERATE BREAK\n",
        command=WP24_TRAIN_MODELING_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.4 loader must verify the pinned assignment-CSV SHA-256",
        path=ROOT / "backend/src/touchline/modeling/dataset.py",
        anchor='    verify_artifact_sha256(data, expected_sha256, "wp2_3_match_assignments.csv")\n',
        replacement="    pass  # DELIBERATE BREAK: assignments-CSV hash check removed\n",
        command=WP24_DATASET_HASH_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.4 loader must verify the pinned cohort-SQL SHA-256",
        path=ROOT / "backend/src/touchline/modeling/dataset.py",
        anchor='    verify_artifact_sha256(data, expected_sha256, "01_model_shot_cohort.sql")\n',
        replacement="    pass  # DELIBERATE BREAK: cohort-SQL hash check removed\n",
        command=WP24_DATASET_HASH_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.4 loader must fail loudly on a non-canonical (CRLF) artifact checkout",
        path=ROOT / "backend/src/touchline/modeling/dataset.py",
        anchor=(
            '    if b"\\r" in data:\n'
            "        raise NonCanonicalArtifactError(\n"
            '            f"{artifact} is not canonical LF (CRLF bytes present). Re-materialize it '
            'from a "\n'
            '            "canonical checkout (see `git add --renormalize` in the WP2.4 contract) '
            'and do not "\n'
            '            "silently normalize inside the loader."\n'
            "        )\n"
        ),
        replacement=(
            '    if b"\\r" in data:\n'
            "        return None  # DELIBERATE BREAK: CRLF silently tolerated\n"
        ),
        command=WP24_DATASET_CRLF_TEST,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.4 shipped candidate must honour D5 (D5=false must not ship full_logistic)",
        path=ROOT / "backend/src/touchline/modeling/train.py",
        anchor='    shipped = "full_logistic" if d5["include"] else "full_minus_presence"\n',
        replacement='    shipped = "full_logistic"  # DELIBERATE BREAK\n',
        command=WP24_TRAIN_MODELING_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.4 shipped feature subset must follow D5 (no presence columns after D5=false)",
        path=ROOT / "backend/src/touchline/modeling/train.py",
        anchor='    shipped_indices = full_columns if d5["include"] else minus_columns\n',
        replacement="    shipped_indices = full_columns  # DELIBERATE BREAK\n",
        command=WP24_TRAIN_MODELING_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.4 results metadata must read from the shipped candidate, not full_logistic",
        path=ROOT / "backend/src/touchline/modeling/train.py",
        anchor='    shipped_key = cast(str, metrics["shipped_candidate"])\n',
        replacement='    shipped_key = "full_logistic"  # DELIBERATE BREAK\n',
        command=WP24_EXPERIMENT_CONSISTENCY_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.4 artifact identity must stay in touchline.modeling.artifact, never __main__",
        path=ROOT / "backend/src/touchline/modeling/artifact.py",
        anchor='ArtifactBundle.__module__ = "touchline.modeling.artifact"\n',
        replacement='ArtifactBundle.__module__ = "__main__"  # DELIBERATE BREAK\n',
        command=WP24_ARTIFACT_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="Inference must enforce the persisted feature-column contract (both bundles)",
        path=ROOT / "backend/src/touchline/modeling/artifact.py",
        anchor="    all_cols = list(all_columns)\n",
        replacement=(
            "    return  # DELIBERATE BREAK: feature-column contract check skipped\n"
            "    all_cols = list(all_columns)\n"
        ),
        command=ARTIFACT_CONTRACT_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="Inference must reject out-of-bounds/negative selected indices (both bundles)",
        path=ROOT / "backend/src/touchline/modeling/artifact.py",
        anchor="    if out_of_range:\n",
        replacement="    if False:  # DELIBERATE BREAK: bounds check skipped\n",
        command=ARTIFACT_CONTRACT_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="Inference must not ignore selected-column/index disagreement (both bundles)",
        path=ROOT / "backend/src/touchline/modeling/artifact.py",
        anchor="    if list(selected_columns) != expected_selected:\n",
        replacement="    if False:  # DELIBERATE BREAK: disagreement ignored\n",
        command=ARTIFACT_CONTRACT_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.4 code commit must come from the repository revision, not the config JSON",
        path=ROOT / "backend/src/touchline/modeling/experiment.py",
        anchor='        code_commit = git(ROOT, "rev-parse", "HEAD")\n',
        replacement="        code_commit = config.code_commit  # DELIBERATE BREAK\n",
        command=WP24_PROVENANCE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.4 input-config SHA-256 must be recorded from the exact input bytes",
        path=ROOT / "backend/src/touchline/modeling/experiment.py",
        anchor="    input_sha = sha256_bytes(input_bytes)\n",
        replacement='    input_sha = "0" * 64  # DELIBERATE BREAK\n',
        command=WP24_PROVENANCE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.4 uv.lock SHA-256 must be recorded",
        path=ROOT / "backend/src/touchline/modeling/experiment.py",
        anchor='    uv_sha = sha256_bytes((ROOT / "uv.lock").read_bytes())\n',
        replacement='    uv_sha = "0" * 64  # DELIBERATE BREAK\n',
        command=WP24_PROVENANCE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.4 published notes must record the canonical repository-relative config path",
        path=ROOT / "backend/src/touchline/modeling/train.py",
        anchor='        f"Input config: {record_path(config.input_config_path)}\\n\\n"\n',
        replacement=(
            '        f"Input config: {config.input_config_path}\\n\\n"  # DELIBERATE BREAK\n'
        ),
        command=WP24_NOTES_PUBLICATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.4 published notes must not point readers at unpublished docs/**",
        path=ROOT / "backend/src/touchline/modeling/train.py",
        anchor='        "- `reports/wp2.4-baselines-evidence.md` — the reviewable WP2.4 evidence '
        'report.\\n\\n"\n',
        replacement=(
            '        "- see docs/modeling/wp2_4-baselines-and-logistic-contract.md\\n\\n"'
            "  # DELIBERATE BREAK\n"
        ),
        command=WP24_NOTES_PUBLICATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.4 machine records must carry the runtime fingerprint",
        path=ROOT / "backend/src/touchline/modeling/train.py",
        anchor=(
            '        "runtime_fingerprint": config.runtime_fingerprint,\n'
            '        "artifact_schema_version": artifact_schema_version,\n'
        ),
        replacement='        "artifact_schema_version": artifact_schema_version,\n',
        command=WP24_EXPERIMENT_CONSISTENCY_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.5 uv.lock identity must resolve at the recorded reproduction commit",
        path=ROOT / "backend/src/touchline/modeling/experiment.py",
        anchor="    return result.stdout\n",
        replacement=(
            "    return (root / relative_path).read_bytes()  "
            "# DELIBERATE BREAK: current working tree\n"
        ),
        command=WP25_ARTIFACT_INTEGRITY_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.5 OpenMP must be pinned to one thread at process start (D20)",
        path=ROOT / "backend/src/touchline/boosting_bootstrap.py",
        anchor="    os.environ[OMP_ENV_VAR] = OMP_THREAD_PIN\n",
        replacement="    pass  # DELIBERATE BREAK: thread pin removed\n",
        command=WP25_PROCESS_DETERMINISM_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.5 must refuse to start under a foreign OpenMP thread count",
        path=ROOT / "backend/src/touchline/boosting_bootstrap.py",
        anchor="    if inherited is not None and inherited.strip() != OMP_THREAD_PIN:\n",
        replacement="    if False:  # DELIBERATE BREAK: foreign thread count tolerated\n",
        command=WP25_PROCESS_DETERMINISM_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.5 boosting must not use early stopping (it would split a locked fold)",
        path=ROOT / "backend/src/touchline/modeling/boosting.py",
        anchor="        early_stopping=EARLY_STOPPING,\n",
        replacement="        early_stopping=True,  # DELIBERATE BREAK\n",
        command=WP25_BOOSTING_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.5 D15 fixed hyperparameters must reach the estimator explicitly",
        path=ROOT / "backend/src/touchline/modeling/boosting.py",
        anchor="        interaction_cst=INTERACTION_CST,\n",
        replacement='        interaction_cst="no_interactions",  # DELIBERATE BREAK\n',
        command=WP25_BOOSTING_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.5 grid selection must follow the total D16 ordering key",
        path=ROOT / "backend/src/touchline/modeling/boosting.py",
        anchor="    best = min(scored, key=_selection_key)\n",
        replacement="    best = scored[0]  # DELIBERATE BREAK: enumeration order\n",
        command=WP25_BOOSTING_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.5 declared search space must not be tunable from the run config (D17)",
        path=ROOT / "backend/src/touchline/modeling/train_boosting.py",
        anchor="    if gbm_grid != GBM_GRID:\n",
        replacement="    if False:  # DELIBERATE BREAK: any grid accepted\n",
        command=WP25_PRE_REGISTRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.5 must refuse to run before the pre-registration is accepted",
        path=ROOT / "backend/src/touchline/modeling/train_boosting.py",
        anchor="        signoff = check_pre_registration()\n",
        replacement="        signoff = UNVERIFIABLE  # DELIBERATE BREAK: gate skipped\n",
        command=WP25_PRE_REGISTRATION_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.5 results row must describe the boosting artifact, not the winner",
        path=ROOT / "backend/src/touchline/modeling/train_boosting.py",
        anchor="    artifact_metrics = cast(_CandidateReadOut, candidates[artifact_key])\n",
        replacement=("    artifact_metrics = cast(_CandidateReadOut, candidates[selection_key])\n"),
        command=WP25_TRAIN_MODELING_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="WP2.5 chain A must extend the WP2.4 chain, not substitute its last step (D18)",
        path=ROOT / "backend/src/touchline/modeling/train_boosting.py",
        anchor=(
            'CHAIN_A_ORDER = ("constant", "geometry_logistic", SHIPPED_LOGISTIC_KEY, GBM_KEY)\n'
        ),
        replacement=(
            'CHAIN_A_ORDER = ("constant", "geometry_logistic", GBM_KEY)  # DELIBERATE BREAK\n'
        ),
        command=WP25_TRAIN_MODELING_TESTS,
        cwd=ROOT,
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


def _invalidate_bytecode(path: Path) -> None:
    """Remove stale ``__pycache__`` entries for one source file.

    A break's test run compiles the mutated source and writes a pyc whose header records the
    source's integer-second mtime. Restoring the original within the same second leaves that pyc
    looking fresh, so a later import silently runs the mutated code while the file shows the
    original — the test suite then fails for reasons that no longer exist. Deleting the pyc makes
    the restore real.
    Python cache files are named for the module plus an interpreter tag — ``splits.cpython-313.pyc``
    — so the glob must be keyed off ``path.stem`` (``splits``), never off ``path.name``
    (``splits.py``), which would match nothing. See ``backend/tests/test_verify_tests_fail.py``.
    """
    cache = path.parent / "__pycache__"
    if not cache.is_dir():
        return
    for pyc in cache.glob(f"{path.stem}.*.pyc"):
        pyc.unlink()


def check(defect: Break) -> bool:
    """Apply one break, run its tests, restore the file. True when the break was caught."""
    original_bytes = defect.path.read_bytes()
    # Normalize line endings for anchor matching, so anchors written with "\n" match both LF and
    # CRLF checkouts (git's autocrlf converts LF checkouts to CRLF on Windows).
    original = defect.path.read_text(encoding="utf-8").replace("\r\n", "\n")
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

    # Byte-exact restore: text-mode writing would translate LF to CRLF on Windows (or be
    # normalized away by git's autocrlf), which both corrupts byte-pinned artifacts such as the
    # WP2.3 assignment CSV and churns every touched file's line endings in the working tree.
    defect.path.write_bytes(mutated.encode("utf-8"))
    try:
        caught = _tests_fail(defect.command, defect.cwd)
    finally:
        defect.path.write_bytes(original_bytes)
        if defect.path.suffix == ".py":
            _invalidate_bytecode(defect.path)

    print(f"[{'CAUGHT' if caught else 'MISSED'}] {defect.contract}")
    return caught


REQUIRED_ENV = (
    ("TOUCHLINE_DB_URL", "integration contracts (they skip without it, and a skip exits zero)"),
    ("TOUCHLINE_FULL_COHORT_DB_URL", "full-cohort contracts (same failure mode)"),
)


def preflight() -> list[str]:
    """Missing prerequisites must not be reportable as survived mutations.

    A skipped test suite exits zero, and this harness reads a zero exit as "the break went
    unnoticed". Without these variables the integration and full-cohort contracts therefore look
    unprotected when they are simply not running.
    """
    return [
        f"{name} is not set - required by the {why}"
        for name, why in REQUIRED_ENV
        if not os.environ.get(name)
    ]


def main() -> int:
    missing = preflight()
    if missing:
        print("Refusing to run: the mutation harness needs a database environment.")
        for line in missing:
            print(f"  - {line}")
        print(
            "Without them, contracts whose tests skip would be scored as MISSED and "
            "read as unprotected behaviour. Set both and run again."
        )
        return 2

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
