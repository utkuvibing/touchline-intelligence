"""Full-cohort contracts for the WP2.4 development loader. Measured evidence, local only.

Like ``test_wp2_3_split_full_cohort.py``, this module creates no schema and seeds nothing: it opens
``READ ONLY`` connections and asserts against the tracked 5,606-row four-tournament cohort that
must already be ingested locally, so it is gated on ``TOUCHLINE_FULL_COHORT_DB_URL``:

    TOUCHLINE_FULL_COHORT_DB_URL='postgresql://touchline:localdev@localhost:5433/touchline' \\
        uv run pytest backend/tests/test_wp2_4_training_full_cohort.py -m full_cohort

GitHub Actions never ingests StatsBomb, so this module skips there. Never point it at the deployed
database (different population → silently different evidence).

What it proves, over the full cohort:

- the locked development anchors through the WP2.4 loader itself: 2,872 shots, 115 matches, fold
  shot sizes {570, 552, 602, 576, 572};
- exact shot-id set equality between the loader and the WP2.1 cohort query restricted to
  development match ids (both directions);
- the structural holdout lock: every loader row's match id is a development match, and neither the
  calibration nor the holdout scope contributes a single row to what the training entry point sees.

The measured protocol result (candidates, D5, incumbent) is produced by ``poe train`` and recorded
in ``reports/wp2.4-baselines-evidence.md``; this module is the data-integrity half of Inc 9.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import psycopg
import pytest

from touchline.modeling.dataset import (
    MatchAssignments,
    load_development_cohort,
    parse_match_assignments,
    verify_assignments_csv,
    verify_cohort_sql,
    verify_development_anchor,
)
from touchline.modeling.preprocessing import ShotRow

FULL_COHORT_DB_URL_VAR = "TOUCHLINE_FULL_COHORT_DB_URL"
DB_URL = os.environ.get(FULL_COHORT_DB_URL_VAR)
ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "data" / "model" / "wp2_3_split_manifest.json"
CSV_PATH = ROOT / "data" / "model" / "wp2_3_match_assignments.csv"
COHORT_SQL_PATH = ROOT / "backend" / "sql" / "wp2_1" / "01_model_shot_cohort.sql"

EXPECTED_SHOTS = 2872
EXPECTED_MATCHES = 115
EXPECTED_FOLD_SIZES = {0: 570, 1: 552, 2: 602, 3: 576, 4: 572}

pytestmark = [
    pytest.mark.integration,
    pytest.mark.full_cohort,
    pytest.mark.skipif(
        DB_URL is None,
        reason=(
            f"{FULL_COHORT_DB_URL_VAR} is not set. These tests measure the loaded 5,606-row "
            "four-tournament cohort and cannot run against an empty or fixture-only database."
        ),
    ),
]


def _manifest() -> dict[str, object]:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _connection() -> psycopg.Connection:
    assert DB_URL is not None
    conn = psycopg.connect(DB_URL, connect_timeout=15)
    conn.read_only = True
    return conn


@pytest.fixture(scope="module")
def cohort() -> tuple[list[ShotRow], MatchAssignments]:
    """The verified assignments, cohort SQL and loaded development rows, computed once."""
    assignments_bytes = CSV_PATH.read_bytes()
    assignments_sha = _manifest()["assignments_sha256"]
    assert isinstance(assignments_sha, str)
    verify_assignments_csv(assignments_bytes, assignments_sha)
    assignments = parse_match_assignments(assignments_bytes.decode("utf-8"))
    cohort_sql_sha = _manifest()["cohort_sql_sha256"]
    assert isinstance(cohort_sql_sha, str)
    cohort_sql = verify_cohort_sql(COHORT_SQL_PATH.read_bytes(), cohort_sql_sha)
    with _connection() as conn:
        rows = load_development_cohort(conn, cohort_sql, assignments)
    return rows, assignments


def test_development_anchors_through_the_loader(
    cohort: tuple[list[ShotRow], MatchAssignments],
) -> None:
    rows, _assignments = cohort
    verify_development_anchor(rows)  # uses the locked constants by default
    assert len(rows) == EXPECTED_SHOTS
    assert len({row.match_id for row in rows}) == EXPECTED_MATCHES


def test_shot_id_set_equality_with_wp21_cohort_restricted_to_development(
    cohort: tuple[list[ShotRow], MatchAssignments],
) -> None:
    rows, assignments = cohort
    wp21_sql = verify_cohort_sql(
        COHORT_SQL_PATH.read_bytes(), str(_manifest()["cohort_sql_sha256"])
    )
    development_ids = assignments.development_match_ids
    with _connection() as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT shot_id, match_id FROM ({wp21_sql.rstrip().rstrip(';')}) AS cohort "
                "ORDER BY shot_id"
            )
            wp21 = cur.fetchall()
    wp21_dev_ids = {str(row[0]) for row in wp21 if int(row[1]) in development_ids}
    loader_ids = {row.shot_id for row in rows}
    assert wp21_dev_ids == loader_ids
    assert len(loader_ids) == EXPECTED_SHOTS


def test_structural_holdout_lock_zero_calibration_or_holdout_rows(
    cohort: tuple[list[ShotRow], MatchAssignments],
) -> None:
    rows, assignments = cohort
    development_ids = assignments.development_match_ids
    assert all(row.match_id in development_ids for row in rows)
    scopes = {row.match_id: (row.competition_id, row.season_id) for row in rows}
    assert all(scope in {(43, 3), (55, 43)} for scope in scopes.values())
    # The full cohort holds calibration (43,106) and holdout (55,282) matches in the database but
    # the loader must never surface them: structural proof of the development-only filter.
    assert not any(scope in {(43, 106), (55, 282)} for scope in scopes.values())


def test_loader_rejects_hash_tampering_on_the_committed_artifact(
    cohort: tuple[list[ShotRow], MatchAssignments],
) -> None:
    from touchline.modeling.dataset import ArtifactHashMismatchError

    data = CSV_PATH.read_bytes()
    with pytest.raises(ArtifactHashMismatchError):
        verify_assignments_csv(data, "0" * 64)


def test_manifest_hashes_match_the_committed_canonical_lf_files() -> None:
    for path, key in (
        (CSV_PATH, "assignments_sha256"),
        (COHORT_SQL_PATH, "cohort_sql_sha256"),
    ):
        data = path.read_bytes()
        assert b"\r" not in data, f"{path.name} must be canonical LF"
        assert hashlib.sha256(data).hexdigest() == _manifest()[key]
