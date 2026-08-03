"""Read-only cohort contract for the WP2.2 Slice A geometry.

Unlike the WP2.1 integration test this module creates no schema, applies no migration and seeds no
fixture. It opens a READ ONLY transaction against whatever database `TOUCHLINE_DB_URL` names and
asserts against rows that are already there, so a write reaching this path fails at the database
rather than succeeding quietly.

Run against the local full-cohort database, never the deployed one:

    TOUCHLINE_DB_URL='postgresql://touchline:localdev@localhost:5433/touchline' \\
        uv run pytest backend/tests/test_wp2_2_geometry_integration.py -m integration
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from touchline.features.geometry import (
    GOAL_LINE_X,
    LEFT_POST_Y,
    MEASURED_MAX_SOURCE_X,
    RIGHT_POST_Y,
    ShotGeometryError,
    distance_to_goal,
    effective_location,
    visible_goal_angle,
)

DB_URL = os.environ.get("TOUCHLINE_DB_URL")
SQL_DIR = Path(__file__).parents[1] / "sql" / "wp2_2"

# WP2.1's locked population. WP2.2 derives features for exactly these rows and changes none of them.
EXPECTED_COHORT_ROWS = 5606

# The single measured source-coordinate exception, identified by the WP2.2 boundary audit.
# Euro 2024 (55, 282), Romania-Ukraine, match 3938638, a Corner shot recorded at (120.1, 0.8).
MEASURED_EXCEPTION_SHOT_ID = "78116cc8-afbe-4bae-975b-57ce6983d045"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(DB_URL is None, reason="TOUCHLINE_DB_URL is not set"),
]


@pytest.fixture(scope="module")
def cohort() -> Iterator[list[tuple[str, int, float, float]]]:
    """Every geometry input row, read inside a READ ONLY transaction."""
    assert DB_URL is not None
    sql = (SQL_DIR / "01_geometry_inputs.sql").read_text(encoding="utf-8")
    with psycopg.connect(DB_URL, connect_timeout=15) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = [
                (str(shot_id), int(match_id), float(raw_x), float(raw_y))
                for shot_id, match_id, raw_x, raw_y in cur.fetchall()
            ]
        conn.rollback()
    yield rows


@pytest.fixture(scope="module")
def audit() -> Iterator[dict[str, float]]:
    """The boundary audit as one row of numbers.

    Every column is a count or a coordinate bound, so they are coerced to float once here rather
    than at each assertion; that keeps the assertions readable as the measurements they are.
    """
    assert DB_URL is not None
    sql = (SQL_DIR / "02_coordinate_boundary_audit.sql").read_text(encoding="utf-8")
    with psycopg.connect(DB_URL, connect_timeout=15) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(sql)
            assert cur.description is not None
            names = [description.name for description in cur.description]
            row = cur.fetchone()
            assert row is not None
        conn.rollback()
    yield {name: float(value) for name, value in zip(names, row, strict=True)}


def test_geometry_inputs_reproduce_the_wp2_1_grain(
    cohort: list[tuple[str, int, float, float]],
) -> None:
    """The anchor that makes every other assertion in this module mean something.

    WP2.2 duplicates WP2.1's predicate set rather than importing it; if the two ever diverge this
    is where it surfaces, before a geometry report is measured on a quietly different population.
    """
    assert len(cohort) == EXPECTED_COHORT_ROWS
    assert len({shot_id for shot_id, _, _, _ in cohort}) == EXPECTED_COHORT_ROWS


def test_audit_agrees_with_the_cohort_query(
    audit: dict[str, float], cohort: list[tuple[str, int, float, float]]
) -> None:
    assert audit["cohort_rows"] == len(cohort) == EXPECTED_COHORT_ROWS
    assert audit["null_x"] == 0
    assert audit["null_y"] == 0


def test_every_cohort_row_produces_finite_features(
    cohort: list[tuple[str, int, float, float]],
) -> None:
    for shot_id, _, raw_x, raw_y in cohort:
        distance = distance_to_goal(raw_x, raw_y)
        angle = visible_goal_angle(raw_x, raw_y)
        assert math.isfinite(distance), shot_id
        assert math.isfinite(angle), shot_id
        assert distance >= 0.0, shot_id


def test_angle_invariant_holds_per_domain(cohort: list[tuple[str, int, float, float]]) -> None:
    """The piecewise contract, checked against each row's own coordinates.

    A blanket `0 <= angle <= pi` would pass while hiding a row on the goal line answering the
    wrong one of the two boundary cases.
    """
    for shot_id, _, raw_x, raw_y in cohort:
        effective_x, y = effective_location(raw_x, raw_y)
        angle = visible_goal_angle(raw_x, raw_y)
        if effective_x < GOAL_LINE_X:
            assert 0.0 < angle < math.pi, shot_id
        elif LEFT_POST_Y < y < RIGHT_POST_Y:
            assert math.isclose(angle, math.pi, rel_tol=0.0, abs_tol=1e-12), shot_id
        else:
            assert angle == 0.0, shot_id


def test_no_cohort_row_sits_exactly_on_a_goalpost(
    audit: dict[str, float], cohort: list[tuple[str, int, float, float]]
) -> None:
    """Counted and reported rather than swallowed: a raise here is a data finding, not a crash."""
    on_post = []
    for shot_id, match_id, raw_x, raw_y in cohort:
        try:
            effective_location(raw_x, raw_y)
        except ShotGeometryError:
            on_post.append((shot_id, match_id, raw_x, raw_y))
    assert on_post == [], f"shots on a goalpost: {on_post}"
    assert audit["shots_on_post_point"] == 0


def test_exactly_one_row_receives_the_bounded_tolerance_adjustment(
    audit: dict[str, float], cohort: list[tuple[str, int, float, float]]
) -> None:
    """The measured source exception, named by shot_id rather than counted anonymously."""
    adjusted = [
        (shot_id, raw_x, raw_y)
        for shot_id, _, raw_x, raw_y in cohort
        if effective_location(raw_x, raw_y)[0] != raw_x
    ]
    assert len(adjusted) == 1
    shot_id, raw_x, raw_y = adjusted[0]
    assert shot_id == MEASURED_EXCEPTION_SHOT_ID
    assert (raw_x, raw_y) == (120.1, 0.8)
    assert effective_location(raw_x, raw_y) == (120.0, 0.8)
    assert math.isclose(distance_to_goal(raw_x, raw_y), 39.2, rel_tol=0.0, abs_tol=1e-12)
    assert visible_goal_angle(raw_x, raw_y) == 0.0

    assert audit["shots_x_gt_120"] == 1
    assert audit["shots_x_ge_120_1"] == 1


def test_no_cohort_row_exceeds_the_measured_source_maximum(audit: dict[str, float]) -> None:
    """The bounded band is bounded by measurement; a new row past it must fail loudly."""
    assert audit["max_x"] <= MEASURED_MAX_SOURCE_X
    assert audit["min_x"] >= 0.0
    assert audit["min_y"] >= 0.0
    assert audit["max_y"] <= 80.0


def test_goal_line_rows_outside_the_posts_keep_zero_angle(
    audit: dict[str, float], cohort: list[tuple[str, int, float, float]]
) -> None:
    on_line = [
        (shot_id, raw_x, raw_y)
        for shot_id, _, raw_x, raw_y in cohort
        if effective_location(raw_x, raw_y)[0] == GOAL_LINE_X
    ]
    assert len(on_line) == audit["shots_x_ge_120"] == 3
    for shot_id, raw_x, raw_y in on_line:
        assert not LEFT_POST_Y <= raw_y <= RIGHT_POST_Y, shot_id
        assert visible_goal_angle(raw_x, raw_y) == 0.0, shot_id


def test_coordinates_are_recorded_in_the_attacking_direction(audit: dict[str, float]) -> None:
    """The specification documents the pitch and goal but states nothing about direction of play.

    Absolute pitch coordinates would put roughly half the shots below the halfway line. Nine of
    5,606 is not that, and the measured minimum x leaves every shot outside the defensive third.
    """
    assert audit["shots_x_lt_60"] == 9
    assert audit["min_x"] > 40.0


def test_the_unstable_region_has_real_support(audit: dict[str, float]) -> None:
    """Why the two-post form is not a theoretical nicety: the naive form fails on 39 real shots."""
    assert audit["shots_inside_h_circle"] == 38
    assert audit["shots_on_h_circle"] == 1
