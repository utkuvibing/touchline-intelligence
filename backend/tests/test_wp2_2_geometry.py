"""Executable contract for the WP2.2 Slice A shot geometry.

Pure unit tests: no database, no network, no fixtures. Every expected value is either derived from
a closed form stated in the test or read directly off the StatsBomb specification diagram, so a
failure points at the implementation rather than at another test's output.

Tolerance policy: every approximate comparison uses ``rel_tol=0.0, abs_tol=1e-12``. Relative
tolerance is deliberately disabled — these are bounded quantities on a 120x80 pitch, and an
absolute bound says what is actually meant.
"""

from __future__ import annotations

import math

import pytest

from touchline.features import geometry
from touchline.features.geometry import (
    GOAL_CENTRE_Y,
    GOAL_LINE_X,
    GOAL_WIDTH,
    LEFT_POST_Y,
    PITCH_WIDTH,
    RIGHT_POST_Y,
    ShotGeometryError,
    distance_to_goal,
    effective_location,
    visible_goal_angle,
)

ABS_TOL = 1e-12
HALF_GOAL = GOAL_WIDTH / 2.0


def close(actual: float, expected: float) -> bool:
    return math.isclose(actual, expected, rel_tol=0.0, abs_tol=ABS_TOL)


def naive_visible_goal_angle(x: float, y: float) -> float:
    """The classic single-arctangent form. Reference only — never used in production code.

    Present so that the failure it produces is reproducible rather than asserted in prose.
    """
    a = GOAL_LINE_X - x
    c = y - GOAL_CENTRE_Y
    return math.atan((GOAL_WIDTH * a) / (a * a + c * c - HALF_GOAL * HALF_GOAL))


def cross_and_dot(x: float, y: float) -> tuple[float, float]:
    a = GOAL_LINE_X - x
    return a * GOAL_WIDTH, a * a + (LEFT_POST_Y - y) * (RIGHT_POST_Y - y)


# ---------------------------------------------------------------------------
# Group 1 - hand-computed cases
#
# Central cases use the closed form 2*atan(h/a), which follows from the isoceles triangle formed
# by the shot and the two posts when the shot is on the y = 40 centre line.
# ---------------------------------------------------------------------------

HAND_COMPUTED = [
    # (x, y, distance, angle, why the angle is what it is)
    (108.0, 40.0, 12.0, 2 * math.atan(HALF_GOAL / 12.0), "penalty spot, per specification p.35"),
    (112.0, 40.0, 8.0, 2 * math.atan(HALF_GOAL / 8.0), "central, 8 out"),
    (116.0, 40.0, 4.0, math.pi / 2, "central, on the dot=0 circle; 2*atan(4/4) = pi/2"),
    (118.0, 40.0, 2.0, 2 * math.atan(HALF_GOAL / 2.0), "central, inside the circle; obtuse"),
    (120.0, 40.0, 0.0, math.pi, "goal line between the posts; goal spans the half-plane"),
    (120.0, 10.0, 30.0, 0.0, "goal line outside the posts; zero visible width"),
    (120.0, 0.0, 40.0, 0.0, "corner flag; zero visible width"),
    (60.0, 0.0, math.hypot(60.0, 40.0), math.atan2(480.0, 5184.0), "far and wide"),
]


@pytest.mark.parametrize(("x", "y", "expected", "_angle", "why"), HAND_COMPUTED)
def test_distance_matches_hand_computed_value(
    x: float, y: float, expected: float, _angle: float, why: str
) -> None:
    assert close(distance_to_goal(x, y), expected), why


@pytest.mark.parametrize(("x", "y", "_distance", "expected", "why"), HAND_COMPUTED)
def test_angle_matches_hand_computed_value(
    x: float, y: float, _distance: float, expected: float, why: str
) -> None:
    assert close(visible_goal_angle(x, y), expected), why


def test_penalty_spot_angle_is_the_three_four_five_triangle() -> None:
    """(108, 40) is the specification's penalty spot and gives tan(angle) = 3/4 exactly."""
    assert close(math.tan(visible_goal_angle(108.0, 40.0)), 0.75)


# ---------------------------------------------------------------------------
# Group 2 - mirror symmetry
#
# Two claims of different strength, kept apart on purpose.
# ---------------------------------------------------------------------------

MIRROR_GRID = [
    (x, y)
    for x in (0.0, 17.5, 45.25, 83.0, 100.0, 110.5, 118.75, 119.9)
    for y in (0.0, 0.7, 12.5, 30.0, 35.999, 39.5)
]

MIRROR_INTEGER_ANCHORS = [(100.0, 30.0), (90.0, 10.0), (110.0, 36.0), (60.0, 0.0)]


@pytest.mark.parametrize(("x", "y"), MIRROR_GRID)
def test_mirror_symmetry_holds_mathematically(x: float, y: float) -> None:
    """2a - the contract. A shot and its reflection across y = 40 are geometrically identical."""
    assert close(distance_to_goal(x, y), distance_to_goal(x, PITCH_WIDTH - y))
    assert close(visible_goal_angle(x, y), visible_goal_angle(x, PITCH_WIDTH - y))


@pytest.mark.parametrize(("x", "y"), MIRROR_INTEGER_ANCHORS)
def test_mirror_symmetry_is_bit_exact_on_integer_anchors(x: float, y: float) -> None:
    """2b - an implementation anchor, NOT a mathematical claim.

    Mathematical symmetry does not require IEEE-754 bit equality; it happens to hold here because
    the current implementation runs the mirrored case through the same multiplications with
    commuted operands, and these inputs are exactly representable. If a refactor breaks this while
    `test_mirror_symmetry_holds_mathematically` still passes, that is a change in arithmetic
    ordering and not a geometry bug: update this anchor, never the contract above.
    """
    assert distance_to_goal(x, y) == distance_to_goal(x, PITCH_WIDTH - y)
    assert visible_goal_angle(x, y) == visible_goal_angle(x, PITCH_WIDTH - y)


# ---------------------------------------------------------------------------
# Group 3 - where the naive form and the stable form agree, and where they do not
#
# Restricted to a > 0, i.e. x < 120. At a = 0 the naive form returns negative zero rather than a
# negative number, and for a < 0 the difference is -pi rather than +pi; both live in Group 4.
# ---------------------------------------------------------------------------

EQUIVALENCE_GRID = [
    (x, y)
    for x in (5.0, 30.0, 60.0, 90.0, 105.0, 112.0, 116.5, 117.0, 118.0, 119.0, 119.5)
    for y in (0.0, 5.0, 20.0, 33.0, 37.0, 40.0, 41.5, 43.0, 55.0, 72.0, 80.0)
]


def test_equivalence_grid_covers_both_sides_of_the_dot_sign() -> None:
    """A guard on the test data itself: an all-positive grid would prove nothing about quadrants."""
    signs = {math.copysign(1.0, cross_and_dot(x, y)[1]) for x, y in EQUIVALENCE_GRID}
    assert signs == {1.0, -1.0}


@pytest.mark.parametrize(("x", "y"), EQUIVALENCE_GRID)
def test_naive_and_stable_agree_where_the_dot_product_is_positive(x: float, y: float) -> None:
    _, dot = cross_and_dot(x, y)
    if dot <= 0.0:
        pytest.skip("covered by the negative-dot test")
    assert close(naive_visible_goal_angle(x, y), visible_goal_angle(x, y))


@pytest.mark.parametrize(("x", "y"), EQUIVALENCE_GRID)
def test_naive_is_negative_and_off_by_pi_where_the_dot_product_is_negative(
    x: float, y: float
) -> None:
    _, dot = cross_and_dot(x, y)
    if dot >= 0.0:
        pytest.skip("covered by the positive-dot test")
    naive = naive_visible_goal_angle(x, y)
    assert naive < 0.0
    assert close(visible_goal_angle(x, y) - naive, math.pi)


def test_naive_divides_by_zero_exactly_on_the_circle() -> None:
    """(116, 40) sits on a**2 + c**2 = h**2. The stable form needs no special case there."""
    _, dot = cross_and_dot(116.0, 40.0)
    assert dot == 0.0
    with pytest.raises(ZeroDivisionError):
        naive_visible_goal_angle(116.0, 40.0)
    assert close(visible_goal_angle(116.0, 40.0), math.pi / 2)


def test_naive_returns_a_negative_angle_two_coordinate_units_from_an_empty_goal() -> None:
    """The headline regression anchor: same cross and dot, opposite conclusions."""
    cross, dot = cross_and_dot(118.0, 40.0)
    assert (cross, dot) == (16.0, -12.0)
    assert close(naive_visible_goal_angle(118.0, 40.0), -0.9272952180016122)
    assert close(visible_goal_angle(118.0, 40.0), 2.214297435588181)


# ---------------------------------------------------------------------------
# Group 4 - boundary policy (x >= 120) and degenerate inputs
# ---------------------------------------------------------------------------

STANCIU_RAW = (120.1, 0.8)


def test_measured_source_exception_is_accepted_via_bounded_adjustment() -> None:
    """The one measured x = 120.1 row: Euro 2024 Romania-Ukraine, shot 78116cc8-...

    Its shot type is Corner, so the recorded location is the corner arc at the intersection of the
    goal line and the touchline, 0.1 behind the goal line. Geometry uses effective_x = 120.0.
    """
    raw_x, raw_y = STANCIU_RAW
    assert effective_location(raw_x, raw_y) == (120.0, 0.8)
    assert close(distance_to_goal(raw_x, raw_y), 39.2)
    assert close(visible_goal_angle(raw_x, raw_y), 0.0)


def test_bounded_adjustment_does_not_mutate_its_input() -> None:
    """The adjustment is a derived-feature decision; the caller's raw coordinates stay raw."""
    raw = list(STANCIU_RAW)
    distance_to_goal(raw[0], raw[1])
    visible_goal_angle(raw[0], raw[1])
    effective_location(raw[0], raw[1])
    assert raw == [120.1, 0.8]


@pytest.mark.parametrize(
    "raw_x",
    [
        120.0 + 1e-13,
        120.05,
        120.1,
        120.1 + 1e-13,
        120.1 + 1e-12,
    ],
)
def test_x_within_the_measured_source_maximum_is_adjusted_to_the_goal_line(raw_x: float) -> None:
    """120.1 is not exactly representable, so the band is admitted with a stated tolerance."""
    assert effective_location(raw_x, 20.0) == (GOAL_LINE_X, 20.0)


@pytest.mark.parametrize("raw_x", [120.2, 120.5, 121.0, 130.0, 240.0])
def test_x_beyond_the_measured_source_maximum_raises(raw_x: float) -> None:
    """No unbounded clamp: past the measured maximum, the source is not what this contract
    was written against."""
    with pytest.raises(ShotGeometryError, match="measured source maximum"):
        effective_location(raw_x, 40.0)
    with pytest.raises(ShotGeometryError):
        distance_to_goal(raw_x, 40.0)
    with pytest.raises(ShotGeometryError):
        visible_goal_angle(raw_x, 40.0)


@pytest.mark.parametrize("y", [0.0, 10.0, 34.2, 35.9999, 44.0001, 54.6, 80.0])
def test_goal_line_outside_the_posts_has_zero_visible_angle(y: float) -> None:
    """Unchanged by the boundary policy. Covers the two measured x = 120.0 cohort rows."""
    assert visible_goal_angle(GOAL_LINE_X, y) == 0.0


@pytest.mark.parametrize("y", [36.0001, 38.0, 40.0, 43.9999])
def test_goal_line_between_the_posts_sees_a_straight_angle(y: float) -> None:
    assert close(visible_goal_angle(GOAL_LINE_X, y), math.pi)


@pytest.mark.parametrize("y", [LEFT_POST_Y, RIGHT_POST_Y])
def test_exact_post_points_raise_rather_than_returning_zero(y: float) -> None:
    """atan2(0.0, 0.0) is 0.0 in Python; 'no visible goal' would be a plausible wrong answer."""
    assert math.atan2(0.0, 0.0) == 0.0  # the trap this guard exists for
    with pytest.raises(ShotGeometryError, match="goalpost"):
        visible_goal_angle(GOAL_LINE_X, y)
    with pytest.raises(ShotGeometryError, match="goalpost"):
        distance_to_goal(GOAL_LINE_X, y)


@pytest.mark.parametrize("y", [LEFT_POST_Y, RIGHT_POST_Y])
def test_post_guard_applies_after_the_bounded_adjustment(y: float) -> None:
    with pytest.raises(ShotGeometryError, match="goalpost"):
        visible_goal_angle(120.05, y)


@pytest.mark.parametrize(
    ("x", "y"),
    [
        (float("nan"), 40.0),
        (60.0, float("nan")),
        (float("inf"), 40.0),
        (60.0, float("-inf")),
    ],
)
def test_non_finite_coordinates_raise(x: float, y: float) -> None:
    with pytest.raises(ShotGeometryError, match="finite"):
        visible_goal_angle(x, y)


@pytest.mark.parametrize(
    ("x", "y"),
    [(-0.1, 40.0), (-1.0, 40.0), (60.0, -0.1), (60.0, 80.1), (60.0, 100.0)],
)
def test_locations_off_the_pitch_raise(x: float, y: float) -> None:
    with pytest.raises(ShotGeometryError, match="outside the pitch"):
        visible_goal_angle(x, y)


# ---------------------------------------------------------------------------
# Group 5 - invariants, stated per domain rather than as one blanket rule
# ---------------------------------------------------------------------------

INVARIANT_GRID = [
    (x, y)
    for x in (0.0, 1.0, 25.0, 48.1, 60.0, 95.5, 110.0, 117.3, 119.0, 119.99)
    for y in (0.0, 0.7, 8.0, 22.5, 36.0, 40.0, 44.0, 61.0, 79.3, 80.0)
]


@pytest.mark.parametrize(("x", "y"), INVARIANT_GRID)
def test_angle_is_strictly_inside_zero_and_pi_short_of_the_goal_line(x: float, y: float) -> None:
    angle = visible_goal_angle(x, y)
    assert math.isfinite(angle)
    assert 0.0 < angle < math.pi


@pytest.mark.parametrize(("x", "y"), INVARIANT_GRID)
def test_distance_is_finite_and_non_negative(x: float, y: float) -> None:
    distance = distance_to_goal(x, y)
    assert math.isfinite(distance)
    assert distance >= 0.0


def test_angle_increases_and_distance_decreases_along_the_centre_line() -> None:
    xs = [40.0, 60.0, 80.0, 100.0, 110.0, 115.0, 118.0, 119.0]
    angles = [visible_goal_angle(x, GOAL_CENTRE_Y) for x in xs]
    distances = [distance_to_goal(x, GOAL_CENTRE_Y) for x in xs]
    assert angles == sorted(angles)
    assert len(set(angles)) == len(angles)
    assert distances == sorted(distances, reverse=True)


def test_angle_decreases_as_the_shot_moves_away_from_the_centre_line() -> None:
    ys = [40.0, 42.0, 46.0, 52.0, 60.0, 70.0, 80.0]
    angles = [visible_goal_angle(110.0, y) for y in ys]
    assert angles == sorted(angles, reverse=True)
    assert len(set(angles)) == len(angles)


def test_module_exposes_the_specification_constants() -> None:
    """Appendix 2 p.36 labels the goalmouth corners (120, 36, 0) and (120, 44, 0)."""
    assert (geometry.GOAL_LINE_X, geometry.LEFT_POST_Y, geometry.RIGHT_POST_Y) == (
        120.0,
        36.0,
        44.0,
    )
    assert geometry.GOAL_WIDTH == 8.0
    assert geometry.GOAL_CENTRE_Y == 40.0
    assert geometry.CROSSBAR_Z == 2.67
