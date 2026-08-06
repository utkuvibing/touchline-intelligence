"""Measured-evidence contracts for WP2.5 against the real ingested four-tournament cohort.

Skipped unless ``TOUCHLINE_FULL_COHORT_DB_URL`` names a database that already holds the ingested
cohort. CI never ingests StatsBomb data, so these are developer-local by construction and say so.

What they protect is the part of the claim a synthetic fixture cannot: that the run consumed the
locked population, that no calibration or holdout row ever reached the fitted input, and that the
committed record's headline figures came from that population rather than from anywhere else.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from touchline.modeling.dataset import (
    LOCKED_DEVELOPMENT_MATCHES,
    LOCKED_DEVELOPMENT_SHOTS,
    LOCKED_FOLD_SHOT_SIZES,
    load_development_cohort,
    parse_match_assignments,
    verify_assignments_csv,
    verify_cohort_sql,
    verify_development_anchor,
)
from touchline.modeling.experiment import open_db
from touchline.modeling.preprocessing import ShotRow
from touchline.modeling.splits import CALIBRATION_SCOPE, DEVELOPMENT_SCOPE, HOLDOUT_SCOPE

DB_URL = os.environ.get("TOUCHLINE_FULL_COHORT_DB_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.full_cohort,
    pytest.mark.skipif(
        DB_URL is None,
        reason=(
            "TOUCHLINE_FULL_COHORT_DB_URL is not set; this needs a database already holding the "
            "ingested four-tournament cohort, which CI deliberately never builds"
        ),
    ),
]

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "experiments" / "shot_quality" / "exp-20260806-wp2_5-gradient-boosting"


@pytest.fixture(scope="module")
def cohort() -> Iterator[list[ShotRow]]:
    metrics = json.loads((EXP / "metrics.json").read_text(encoding="utf-8"))
    csv_bytes = (ROOT / "data" / "model" / "wp2_3_match_assignments.csv").read_bytes()
    verify_assignments_csv(csv_bytes, metrics["assignments_sha256"])
    assignments = parse_match_assignments(csv_bytes.decode("utf-8"))
    sql = verify_cohort_sql(
        (ROOT / "backend" / "sql" / "wp2_1" / "01_model_shot_cohort.sql").read_bytes(),
        metrics["cohort_sql_sha256"],
    )
    assert DB_URL is not None
    conn = open_db(DB_URL)
    try:
        yield load_development_cohort(conn, sql, assignments)
    finally:
        conn.close()


def test_the_locked_development_anchors_still_hold(cohort: list[ShotRow]) -> None:
    verify_development_anchor(cohort)
    assert len(cohort) == LOCKED_DEVELOPMENT_SHOTS
    assert len({row.match_id for row in cohort}) == LOCKED_DEVELOPMENT_MATCHES
    sizes: dict[int, int] = {}
    for row in cohort:
        assert row.fold is not None
        sizes[row.fold] = sizes.get(row.fold, 0) + 1
    assert sizes == dict(LOCKED_FOLD_SHOT_SIZES)


def test_no_calibration_or_holdout_row_reaches_the_fitted_input(cohort: list[ShotRow]) -> None:
    """The structural lock, checked against the data rather than against the loader's intent."""
    scopes = {(row.competition_id, row.season_id) for row in cohort}
    assert scopes == set(DEVELOPMENT_SCOPE)
    assert CALIBRATION_SCOPE not in scopes
    assert HOLDOUT_SCOPE not in scopes


def test_the_cohort_row_order_is_total_and_ascending(cohort: list[ShotRow]) -> None:
    """Reproducibility of the artifact depends on the loader's order being fully determined."""
    ids = [row.shot_id for row in cohort]
    assert len(set(ids)) == len(ids), "a duplicate shot_id would make ORDER BY a partial order"
    assert ids == sorted(ids)


def test_the_committed_record_describes_this_population(cohort: list[ShotRow]) -> None:
    metrics = json.loads((EXP / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["n_rows"] == len(cohort)
    assert metrics["n_matches"] == len({row.match_id for row in cohort})
    prevalence = sum(row.y for row in cohort) / len(cohort)
    recorded = metrics["candidates"]["hist_gbm"]["pooled_oof"]["prevalence"]
    assert abs(recorded - prevalence) < 1e-12
