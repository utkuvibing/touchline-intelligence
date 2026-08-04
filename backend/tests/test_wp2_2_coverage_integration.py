"""Read-only coverage and annotation-semantics contract for WP2.2 Slice B.

Like `test_wp2_2_geometry_integration.py`, this module creates no schema, applies no migration and
seeds no fixture. It opens a ``READ ONLY`` transaction and asserts against the 5,606 rows that must
*already* be there, so it is gated on ``TOUCHLINE_FULL_COHORT_DB_URL`` rather than on
``TOUCHLINE_DB_URL``:

    TOUCHLINE_FULL_COHORT_DB_URL='postgresql://touchline:localdev@localhost:5433/touchline' \\
        uv run pytest backend/tests/test_wp2_2_coverage_integration.py -m full_cohort

What it protects is a decision, not a computation. The WP2.2 plan admits context features only
after coverage is documented, and WP2.1 left six boolean fields `Uncertain` pending their
absent-versus-false encoding. The measured answer is that none of the six ever records an explicit
``false``. Every downstream treatment of those fields depends on that staying true of the pinned
source revision, so it is asserted here rather than written down and trusted.

Neither query under test reads or projects the target. Level and field admissibility is decided
from support and encoding; the conversion rates that would decide it from the outcome are
measurable over a cohort that contains WP2.3's holdout.

That is a property of these queries, not a claim about the whole development process: aggregate
outcome rates by candidate context level were viewed during untracked exploratory work before the
split was frozen. See "Target access" in `reports/wp2.2-slice-b-coverage-evidence.md`.

Never point this at the deployed database. Every statement here is read-only, but the deployed
instance holds a different population and would silently produce different evidence.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

#: Deliberately NOT ``TOUCHLINE_DB_URL``. See the module docstring.
FULL_COHORT_DB_URL_VAR = "TOUCHLINE_FULL_COHORT_DB_URL"

DB_URL = os.environ.get(FULL_COHORT_DB_URL_VAR)
SQL_DIR = Path(__file__).parents[1] / "sql" / "wp2_2"

# WP2.1's locked population. Slice B documents coverage over exactly these rows and changes none.
EXPECTED_COHORT_ROWS = 5606

CATEGORICAL_FIELDS = (
    "body_part_name",
    "play_pattern_name",
    "shot_type_name",
    "technique_name",
)

CANDIDATE_BOOLEANS = (
    "aerial_won",
    "first_time",
    "follows_dribble",
    "one_on_one",
    "open_goal",
    "under_pressure",
)

# (field, value, shots, wc_2018, euro_2020, wc_2022, euro_2024), in the query's declared order.
EXPECTED_CATEGORICAL_SUPPORT = [
    ("body_part_name", "Right Foot", 2865, 825, 632, 732, 676),
    ("body_part_name", "Left Foot", 1692, 489, 377, 433, 393),
    ("body_part_name", "Head", 1011, 310, 221, 252, 228),
    ("body_part_name", "Other", 38, 14, 4, 13, 7),
    ("play_pattern_name", "Regular Play", 1941, 654, 411, 446, 430),
    ("play_pattern_name", "From Free Kick", 1071, 309, 234, 285, 243),
    ("play_pattern_name", "From Throw In", 1016, 257, 230, 298, 231),
    ("play_pattern_name", "From Corner", 934, 279, 208, 223, 224),
    ("play_pattern_name", "From Goal Kick", 233, 42, 51, 80, 60),
    ("play_pattern_name", "From Counter", 228, 60, 56, 56, 56),
    ("play_pattern_name", "From Keeper", 103, 22, 22, 21, 38),
    ("play_pattern_name", "From Kick Off", 65, 13, 16, 17, 19),
    ("play_pattern_name", "Other", 15, 2, 6, 4, 3),
    ("shot_type_name", "Open Play", 5388, 1556, 1193, 1382, 1257),
    ("shot_type_name", "Free Kick", 212, 82, 41, 46, 43),
    ("shot_type_name", "Corner", 6, 0, 0, 2, 4),
    ("technique_name", "Normal", 4443, 1361, 948, 1087, 1047),
    ("technique_name", "Half Volley", 685, 118, 186, 212, 169),
    ("technique_name", "Volley", 350, 117, 76, 92, 65),
    ("technique_name", "Lob", 42, 11, 6, 13, 12),
    ("technique_name", "Diving Header", 36, 12, 8, 14, 2),
    ("technique_name", "Overhead Kick", 30, 13, 4, 7, 6),
    ("technique_name", "Backheel", 20, 6, 6, 5, 3),
]

# (field, recorded_true, recorded_false, absent, true per tournament), in the query's order.
EXPECTED_ANNOTATION_ENCODING = [
    ("aerial_won", 520, 0, 5086, 124, 134, 129, 133),
    ("first_time", 1599, 0, 4007, 357, 394, 468, 380),
    ("follows_dribble", 7, 0, 5599, 2, 1, 3, 1),
    ("one_on_one", 229, 0, 5377, 55, 43, 79, 52),
    ("open_goal", 54, 0, 5552, 17, 15, 13, 9),
    ("under_pressure", 1259, 0, 4347, 329, 305, 238, 387),
]

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


#: (field, value, shots, wc_2018, euro_2020, wc_2022, euro_2024)
SupportRow = tuple[str, str, int, int, int, int, int]
#: (field, recorded_true, recorded_false, absent, true per tournament)
EncodingRow = tuple[str, int, int, int, int, int, int, int]


def _read_only_rows(filename: str) -> list[tuple[object, ...]]:
    """Run one WP2.2 query inside a READ ONLY transaction and return its rows verbatim."""
    assert DB_URL is not None
    sql = (SQL_DIR / filename).read_text(encoding="utf-8")
    with psycopg.connect(DB_URL, connect_timeout=15) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = [tuple(row) for row in cur.fetchall()]
        conn.rollback()
    return rows


def _count(value: object) -> int:
    """Every numeric column in both queries is a `count(*)`, so anything else is a query change."""
    assert isinstance(value, int), value
    return value


@pytest.fixture(scope="module")
def support() -> Iterator[list[SupportRow]]:
    """Coerced once here, as the geometry module does, so assertions read as measurements."""
    yield [
        (str(field), str(value), *(_count(n) for n in counts))  # type: ignore[misc]
        for field, value, *counts in _read_only_rows("03_categorical_support.sql")
    ]


@pytest.fixture(scope="module")
def encoding() -> Iterator[list[EncodingRow]]:
    yield [
        (str(field), *(_count(n) for n in counts))  # type: ignore[misc]
        for field, *counts in _read_only_rows("04_annotation_encoding_audit.sql")
    ]


def test_categorical_support_reproduces_the_wp2_1_grain(support: list[SupportRow]) -> None:
    """The anchor that makes every other assertion here mean something.

    Slice B duplicates WP2.1's predicate set rather than importing it, exactly as Slice A does. If
    the two diverge, this fails before a coverage decision is taken on a quietly different
    population. Each field partitions the same cohort, so each field's levels must sum to it.
    """
    totals: dict[str, int] = {}
    for field, _value, shots, *_ in support:
        totals[field] = totals.get(field, 0) + shots

    assert set(totals) == set(CATEGORICAL_FIELDS)
    for field in CATEGORICAL_FIELDS:
        assert totals[field] == EXPECTED_COHORT_ROWS, field


def test_categorical_support_matches_the_measured_levels(support: list[SupportRow]) -> None:
    assert support == EXPECTED_CATEGORICAL_SUPPORT


def test_per_tournament_columns_partition_each_level(support: list[SupportRow]) -> None:
    """The four tournament columns are a partition, not an overlapping selection.

    If they ever stop summing to the level total, the scope CTE has admitted a fifth
    competition/season pair and every per-tournament reading below is measuring something else.
    """
    for field, value, shots, *by_tournament in support:
        assert sum(by_tournament) == shots, (field, value)


def test_no_candidate_boolean_ever_records_an_explicit_false(encoding: list[EncodingRow]) -> None:
    """The executable form of WP2.1's unresolved absent-versus-false question.

    Ingestion maps an absent JSON key to NULL and never invents a value, so a provider-recorded
    ``false`` would arrive as FALSE. None does. That makes these fields true-only annotations:
    absence cannot be separated from "annotated as not the case", and anything built on them is a
    presence indicator rather than a boolean.

    If a future pinned revision starts recording explicit ``false``, this fails -- which is the
    point. The semantics decision would then have to be retaken rather than inherited.
    """
    recorded_false = {field: false_count for field, _true, false_count, *_ in encoding}

    assert set(recorded_false) == set(CANDIDATE_BOOLEANS)
    assert recorded_false == dict.fromkeys(CANDIDATE_BOOLEANS, 0)


def test_true_false_and_absent_partition_the_cohort(encoding: list[EncodingRow]) -> None:
    """Three-way SQL NULL counting is easy to get wrong; this proves nothing was double-counted."""
    for field, true_count, false_count, absent, *_ in encoding:
        assert true_count + false_count + absent == EXPECTED_COHORT_ROWS, field


def test_annotation_encoding_matches_the_measured_counts(encoding: list[EncodingRow]) -> None:
    assert encoding == EXPECTED_ANNOTATION_ENCODING


def test_only_the_corner_shot_type_is_missing_from_a_whole_tournament(
    support: list[SupportRow],
) -> None:
    """The finding WP2.3's split design has to be handed, derived rather than restated.

    A level absent from an entire tournament is a level a tournament-grouped fold can meet without
    ever having trained on it. Exactly one such level exists in this cohort, and naming the set
    here means a second one appearing in a future revision fails rather than passes quietly.
    """
    absent_somewhere = {
        (field, value)
        for field, value, _shots, *by_tournament in support
        if any(n == 0 for n in by_tournament)
    }

    assert absent_somewhere == {("shot_type_name", "Corner")}
