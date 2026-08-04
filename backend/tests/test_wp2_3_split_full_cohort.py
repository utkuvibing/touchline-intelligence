"""Full-cohort contracts for the WP2.3 split lock. Measured evidence, local only.

Like `test_wp2_2_coverage_integration.py`, this module creates no schema, applies no migration and
seeds no fixture. It opens ``READ ONLY`` connections and asserts against the 5,606 eligible rows
that must *already* be there, so it is gated on ``TOUCHLINE_FULL_COHORT_DB_URL`` rather than on
``TOUCHLINE_DB_URL``:

    TOUCHLINE_FULL_COHORT_DB_URL='postgresql://touchline:localdev@localhost:5433/touchline' \\
        uv run pytest backend/tests/test_wp2_3_split_full_cohort.py -m full_cohort

GitHub Actions does not run these tests: CI never ingests the StatsBomb dataset, so the module
skips there with that reason stated. Never point this at the deployed database — every statement
here is read-only, but the deployed instance holds a different population and would silently
produce different evidence.

What it proves, over exactly the locked four-tournament cohort:

- the match population anchors (230 matches; 115/64/51 per top-level split; 5,606 eligible shots);
- the true shot-level partition proof: every eligible shot id joins exactly one match assignment
  and exactly one top-level split, with no duplicates and no unassigned shots;
- exact set equality between the WP2.1 cohort query's shot ids and this module's shot-membership
  query, and per-match eligible-shot agreement between the two WP2.3 queries for all 230 matches;
- the fold lock (5 deterministic match-grouped folds of 23 development matches each), the strict
  top-level chronology, NULL-date absence, and determinism under row-order changes;
- byte-for-byte agreement of the committed assignment CSV with a fresh recomputation, and the
  manifest's exact allowed-key schema at every nesting level with every value independently
  recomputed.

**Target honesty boundary.** The WP2.1 cohort query is executed here solely to compare `shot_id`
sets (its first column); only that column is consumed. No outcome value enters WP2.3's split
logic, artifacts, protocol decisions, or assertions. That is not a claim that no target-bearing
historical query was ever executed: WP2.1's published reconciliation read the target, and that
exposure is disclosed in `docs/modeling/wp2_3-split-and-evaluation-contract.md`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import psycopg
import pytest

from touchline.ingest.source import SOURCE_COMMIT
from touchline.modeling.splits import (
    CALIBRATION_SCOPE,
    DEVELOPMENT_SCOPE,
    HOLDOUT_SCOPE,
    N_FOLDS,
    MatchRecord,
    SplitPlan,
    assign_tournament_split,
    manifest_summaries,
    render_match_assignments_csv,
)

#: Deliberately NOT ``TOUCHLINE_DB_URL``. See the module docstring.
FULL_COHORT_DB_URL_VAR = "TOUCHLINE_FULL_COHORT_DB_URL"

DB_URL = os.environ.get(FULL_COHORT_DB_URL_VAR)
SQL_DIR = Path(__file__).parents[1] / "sql" / "wp2_3"
WP21_SQL_DIR = Path(__file__).parents[1] / "sql" / "wp2_1"
ROOT = Path(__file__).parents[2]
CSV_PATH = ROOT / "data" / "model" / "wp2_3_match_assignments.csv"
MANIFEST_PATH = ROOT / "data" / "model" / "wp2_3_split_manifest.json"
COHORT_SQL_PATH = WP21_SQL_DIR / "01_model_shot_cohort.sql"

EXPECTED_COHORT_ROWS = 5606
EXPECTED_MATCHES = 230
EXPECTED_SPLIT_SIZES = {"development": 115, "calibration": 64, "holdout": 51}
EXPECTED_SPLIT_SHOTS = {"development": 2872, "calibration": 1430, "holdout": 1304}
EXPECTED_FOLD_SIZE = 23
SPLIT_NAMES: tuple[Literal["development", "calibration", "holdout"], ...] = (
    "development",
    "calibration",
    "holdout",
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.full_cohort,
    pytest.mark.skipif(
        DB_URL is None,
        reason=(
            f"{FULL_COHORT_DB_URL_VAR} is not set. These tests measure the loaded 5,606-row "
            "four-tournament cohort and cannot run against an empty or fixture-only database. "
            "Set it to a local PostgreSQL that has been migrated and ingested, e.g. "
            "postgresql://touchline:localdev@localhost:5433/touchline"
        ),
    ),
]

#: The exact allowed-key schema of the split manifest, mirrored at every nesting level.
#: A leaf is ``None``; a nested dict declares the only keys that level may carry. Unexpected or
#: missing keys at any level must fail validation.
MANIFEST_KEY_SCHEMA: dict[str, object] = {
    "split_name": None,
    "version": None,
    "source_commit": None,
    "cohort_sql_sha256": None,
    "generated_utc": None,
    "rule": {
        "holdout_scope": None,
        "calibration_scope": None,
        "development_scopes": None,
        "n_folds": None,
        "fold_assignment": None,
        "fold_semantics": None,
    },
    "splits": {
        "development": {
            "matches": None,
            "eligible_shots": None,
            "date_first": None,
            "date_last": None,
        },
        "calibration": {
            "matches": None,
            "eligible_shots": None,
            "date_first": None,
            "date_last": None,
        },
        "holdout": {
            "matches": None,
            "eligible_shots": None,
            "date_first": None,
            "date_last": None,
        },
    },
    "folds": {
        "0": {"matches": None, "date_first": None, "date_last": None},
        "1": {"matches": None, "date_first": None, "date_last": None},
        "2": {"matches": None, "date_first": None, "date_last": None},
        "3": {"matches": None, "date_first": None, "date_last": None},
        "4": {"matches": None, "date_first": None, "date_last": None},
    },
    "assignments_sha256": None,
    "attribution": None,
}


def _int(value: object) -> int:
    assert isinstance(value, int), value
    return value


def _date_value(value: object) -> dt.date:
    assert isinstance(value, dt.date), value
    return value


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_only_rows(filename: str, sql_dir: Path | None = None) -> list[tuple[object, ...]]:
    """Run one query inside a READ ONLY connection and return its rows verbatim."""
    assert DB_URL is not None
    sql = (
        (sql_dir if sql_dir is not None else SQL_DIR).joinpath(filename).read_text(encoding="utf-8")
    )
    with psycopg.connect(DB_URL, connect_timeout=15) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = [tuple(row) for row in cur.fetchall()]
        conn.rollback()
    return rows


@dataclass(frozen=True, slots=True)
class _Population:
    """The measured match population plus the computed split plan."""

    match_rows: list[tuple[object, ...]]
    eligible_shots: dict[int, int]
    records: list[MatchRecord]
    plan: SplitPlan


@pytest.fixture(scope="module")
def population() -> Iterator[_Population]:
    """Coerced once here, as the WP2.2 coverage module does, so assertions read as measurements."""
    rows = _read_only_rows("01_split_match_population.sql")
    eligible_shots = {_int(row[0]): _int(row[4]) for row in rows}
    records = [
        MatchRecord(
            match_id=_int(row[0]),
            competition_id=_int(row[1]),
            season_id=_int(row[2]),
            match_date=_date_value(row[3]),
        )
        for row in rows
    ]
    yield _Population(
        match_rows=rows,
        eligible_shots=eligible_shots,
        records=records,
        plan=assign_tournament_split(records),
    )


def test_match_population_anchors(population: _Population) -> None:
    assert len(population.match_rows) == EXPECTED_MATCHES
    sizes = {split: len(population.plan.matches_in(split)) for split in SPLIT_NAMES}
    assert sizes == EXPECTED_SPLIT_SIZES
    assert sum(population.eligible_shots.values()) == EXPECTED_COHORT_ROWS
    per_split_shots = {
        split: sum(population.eligible_shots.get(m, 0) for m in population.plan.matches_in(split))
        for split in SPLIT_NAMES
    }
    assert per_split_shots == EXPECTED_SPLIT_SHOTS


def test_plan_keys_partition_all_cohort_matches(population: _Population) -> None:
    match_ids = {_int(row[0]) for row in population.match_rows}
    assert set(population.plan.match_split) == match_ids
    assert len(set(population.plan.match_split.values())) == 3


def test_shot_level_partition_proof(population: _Population) -> None:
    """Every eligible shot id joins exactly one match assignment and exactly one split.

    This is a per-shot proof, not an aggregate: shot ids are unique, each row's match is assigned,
    and each shot lands in exactly one top-level split. There are no duplicates and no unassigned
    shots, and the per-split totals are the locked ones.
    """
    rows = _read_only_rows("02_split_shot_membership.sql")
    assert len(rows) == EXPECTED_COHORT_ROWS
    shot_ids = [row[0] for row in rows]
    assert len(shot_ids) == len(set(shot_ids))
    for row in rows:
        assert _int(row[1]) in population.plan.match_split
    per_split_shots = {"development": 0, "calibration": 0, "holdout": 0}
    for row in rows:
        per_split_shots[population.plan.split_of(_int(row[1]))] += 1
    assert per_split_shots == EXPECTED_SPLIT_SHOTS
    shot_match_ids = {_int(row[1]) for row in rows}
    assert shot_match_ids <= set(population.plan.match_split)
    matches_with_shots = {m for m, count in population.eligible_shots.items() if count > 0}
    assert shot_match_ids == matches_with_shots


def test_shot_membership_is_set_equal_to_the_wp21_cohort(population: _Population) -> None:
    """Exact set equality between the canonical WP2.1 cohort ids and the WP2.3 query.

    Only the ``shot_id`` column (row 0) of the WP2.1 query is consumed. Equality is asserted in
    both directions: no eligible shot is missing from the WP2.3 query and none is admitted that
    WP2.1 excludes.
    """
    wp21_rows = _read_only_rows("01_model_shot_cohort.sql", sql_dir=WP21_SQL_DIR)
    wp23_rows = _read_only_rows("02_split_shot_membership.sql")

    wp21_ids = {row[0] for row in wp21_rows}
    wp23_ids = {row[0] for row in wp23_rows}
    assert len(wp21_ids) == EXPECTED_COHORT_ROWS
    assert wp21_ids == wp23_ids
    assert len(wp23_ids) == EXPECTED_COHORT_ROWS


def test_per_match_count_agreement_between_the_two_queries(population: _Population) -> None:
    """Query 01's eligible_shots equals query 02 grouped by match, for every one of the 230."""
    rows_02 = _read_only_rows("02_split_shot_membership.sql")
    grouped: dict[int, int] = {}
    for row in rows_02:
        match_id = _int(row[1])
        grouped[match_id] = grouped.get(match_id, 0) + 1
    for match_id, shots in population.eligible_shots.items():
        assert grouped.get(match_id, 0) == shots, match_id
    assert set(grouped) <= set(population.eligible_shots)


def test_five_deterministic_match_grouped_folds_of_23(population: _Population) -> None:
    fold_ids: dict[int, set[int]] = {fold: set() for fold in range(N_FOLDS)}
    for match_id, fold in population.plan.match_fold.items():
        fold_ids[fold].add(match_id)
    assert set(population.plan.match_fold) == set(population.plan.matches_in("development"))
    for fold in range(N_FOLDS):
        assert len(fold_ids[fold]) == EXPECTED_FOLD_SIZE, fold
    for a in range(N_FOLDS):
        for b in range(a + 1, N_FOLDS):
            assert not fold_ids[a] & fold_ids[b]
    union = set().union(*fold_ids.values())
    assert union == set(population.plan.matches_in("development"))
    assert not union & set(population.plan.matches_in("calibration"))
    assert not union & set(population.plan.matches_in("holdout"))


def test_strict_chronology_between_top_level_splits(population: _Population) -> None:
    """Development < calibration < holdout, measured on the real match dates."""
    dates_by_match = {
        record.match_id: _date_value(record.match_date) for record in population.records
    }
    dev_dates = {dates_by_match[m] for m in population.plan.matches_in("development")}
    calib_dates = {dates_by_match[m] for m in population.plan.matches_in("calibration")}
    holdout_dates = {dates_by_match[m] for m in population.plan.matches_in("holdout")}
    assert max(dev_dates) < min(calib_dates)
    assert max(calib_dates) < min(holdout_dates)
    assert max(holdout_dates) <= dt.date(2024, 12, 31)


def test_no_null_match_dates(population: _Population) -> None:
    """The assignment would raise on a NULL date; on the real cohort it must not."""
    assert all(record.match_date is not None for record in population.records)


def test_assignment_is_deterministic_under_row_order_changes(population: _Population) -> None:
    assert assign_tournament_split(list(reversed(population.records))) == population.plan
    rotated = population.records[40:] + population.records[:40]
    assert assign_tournament_split(rotated) == population.plan


def test_committed_assignment_csv_is_byte_pinned(population: _Population) -> None:
    """A fresh recomputation from the database reproduces the committed CSV byte for byte."""
    rendered = render_match_assignments_csv(population.plan, population.records)
    assert rendered.encode("utf-8") == CSV_PATH.read_bytes()


def test_manifest_schema_and_values_are_exact(population: _Population) -> None:
    """The manifest obeys the exact allowed-key schema at every level and every field is
    independently recomputed from the database. Only ``generated_utc`` is a timestamp: it must
    parse, but regenerated manifests are not byte-identical by design."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    _assert_matches_schema(manifest, MANIFEST_KEY_SCHEMA)

    assert manifest["split_name"] == "wp2_3_tournament_split"
    assert manifest["version"] == 1
    assert manifest["source_commit"] == SOURCE_COMMIT
    assert manifest["attribution"] == "Data provided by StatsBomb."
    assert manifest["cohort_sql_sha256"] == _sha256_file(COHORT_SQL_PATH)
    assert manifest["rule"]["n_folds"] == N_FOLDS
    assert manifest["rule"]["holdout_scope"] == list(HOLDOUT_SCOPE)
    assert manifest["rule"]["calibration_scope"] == list(CALIBRATION_SCOPE)
    assert manifest["rule"]["development_scopes"] == sorted(
        list(scope) for scope in DEVELOPMENT_SCOPE
    )
    dt.datetime.fromisoformat(str(manifest["generated_utc"]))

    splits, folds = manifest_summaries(
        population.plan, population.records, population.eligible_shots
    )
    assert manifest["splits"] == splits
    assert manifest["folds"] == folds
    assert manifest["assignments_sha256"] == _sha256_file(CSV_PATH)


def test_wp23_sql_files_reference_no_outcome(population: _Population) -> None:
    """Neither WP2.3 query may project the target.

    The duplicated WP2.1 eligibility predicate necessarily references ``outcome_name`` once, in
    its ``IS NOT NULL`` form — removing it would break the cohort set-equality proof. The check
    therefore allows exactly that single predicate occurrence and forbids any other reference,
    including any projection.
    """
    for filename in ("01_split_match_population.sql", "02_split_shot_membership.sql"):
        lines = (SQL_DIR / filename).read_text(encoding="utf-8").splitlines()
        assert "is_goal" not in "\n".join(lines), filename
        outcome_lines = [line for line in lines if "outcome_name" in line]
        assert len(outcome_lines) == 1, filename
        assert outcome_lines[0].strip() == "AND s.outcome_name IS NOT NULL", filename


def _assert_matches_schema(actual: object, schema: dict[str, object], path: str = "$") -> None:
    """Recursively require the exact key set at every dict level; unexpected keys must fail."""
    if not isinstance(actual, dict):
        raise AssertionError(f"{path}: expected an object, got {type(actual).__name__}")
    actual_keys = set(actual)
    expected_keys = set(schema)
    assert actual_keys == expected_keys, f"{path}: keys {actual_keys ^ expected_keys} differ"
    for key, child_schema in schema.items():
        if isinstance(child_schema, dict):
            _assert_matches_schema(actual[key], child_schema, f"{path}.{key}")
