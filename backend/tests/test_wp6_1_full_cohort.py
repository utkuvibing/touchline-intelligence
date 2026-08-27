"""Read-only full-cohort acceptance for the WP6.1 context and audit seam."""

from __future__ import annotations

import os

import psycopg
import pytest

from touchline.modeling.v2_folds import load_gate_config
from touchline.modeling.wp6_1_audit import build_coverage_report, load_feature_dictionary
from touchline.modeling.wp6_1_context import load_v2_contexts
from touchline.validation_tiers import is_local_postgres_url

DB_URL = os.environ.get("TOUCHLINE_FULL_COHORT_DB_URL")
EXPECTED_BY_TOURNAMENT = {
    "WC2018": 1638,
    "Euro2020": 1234,
    "WC2022": 1430,
    "Euro2024": 1304,
}

pytestmark = [
    pytest.mark.integration,
    pytest.mark.full_cohort,
    pytest.mark.skipif(
        DB_URL is None,
        reason="TOUCHLINE_FULL_COHORT_DB_URL is not set for the 5,606-row WP6.1 acceptance",
    ),
]


def test_full_cohort_context_and_audit_are_deterministic() -> None:
    assert DB_URL is not None
    assert is_local_postgres_url(DB_URL), "full-cohort WP6.1 acceptance refuses deployed databases"
    with psycopg.connect(DB_URL, connect_timeout=15) as conn:
        conn.read_only = True
        contexts = load_v2_contexts(conn, load_gate_config())

    assert len(contexts) == 5606
    assert len({item.metadata.shot_id for item in contexts}) == 5606
    report = build_coverage_report(contexts, load_feature_dictionary())
    assert report.contexts_by_tournament == EXPECTED_BY_TOURNAMENT
    assert report.total_contexts == 5606
    first_shot_after_france_own_goal = next(
        item for item in contexts if item.metadata.shot_id == "9a186aed-c21d-4222-b527-dafbe14a658a"
    )
    assert first_shot_after_france_own_goal.context.team_score_before == 0
    assert first_shot_after_france_own_goal.context.opponent_score_before == 1
    assert (
        report.to_json()
        == build_coverage_report(reversed(contexts), load_feature_dictionary()).to_json()
    )
