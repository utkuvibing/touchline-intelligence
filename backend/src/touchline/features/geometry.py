"""Shot geometry: distance to the goal centre and the visible goal angle.

Two pure functions over a single recorded shot location. No database, no network, no target, no
fitted state — the same call with the same input returns the same float on any machine, which is
what lets WP2.3's splits and WP2.4's baseline treat these as fixed inputs rather than as something
that has to be re-derived and re-argued later.

**Why the two-post form.** The classic single-arctangent expression for the visible goal angle is

    atan((GOAL_WIDTH * a) / (a**2 + c**2 - h**2))

where ``a`` is the distance to the goal line, ``c`` the lateral offset from the goal centre and
``h`` the half goal width. Expanding the two-post vectors shows that its numerator is exactly the
cross product of those vectors and its denominator exactly their dot product. So the naive form is
``atan(cross / dot)`` and the form used here is ``atan2(cross, dot)``: the entire difference is that
dividing throws away the sign of the denominator, and with it the quadrant.

That matters on real rows, not just in theory. ``dot < 0`` is exactly the region inside a circle of
radius ``h`` around the goal centre, and the pinned cohort has 38 shots inside it plus one exactly
on its boundary. Inside, the naive form returns a *negative* angle for a shot that in fact sees an
obtuse slice of goal; on the boundary it divides by zero. `atan2` needs no branch for either.

The naive form is not implemented here. It lives in the test module as a reference implementation
whose only job is to make the failure reproducible.
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# Pitch and goal constants
#
# Source: StatsBomb Open Data Specification v1.1, Appendix 2 "Locations", checked 2026-08-03.
# Page 35 ("Pitch Coordinates") gives the pitch as (0,0)-(120,80) with the centre spot at (60,40)
# and the penalty spot at (108,40); page 36 ("Goal Coordinates") labels the goalmouth corners
# (120, 36, 0), (120, 44, 0), (120, 36, 2.67) and (120, 44, 2.67).
#
# Both appendix pages carry these numbers as diagrams rather than prose, so they are recorded here
# and in docs/modeling/wp2_2-geometry-contract.md instead of being left implicit in the formulas.
# ---------------------------------------------------------------------------

PITCH_LENGTH = 120.0
PITCH_WIDTH = 80.0

GOAL_LINE_X = 120.0
GOAL_CENTRE_Y = 40.0
LEFT_POST_Y = 36.0
RIGHT_POST_Y = 44.0
GOAL_WIDTH = RIGHT_POST_Y - LEFT_POST_Y
CROSSBAR_Z = 2.67  # Recorded for completeness; Slice A is two-dimensional and never reads it.

# The one measured source-coordinate exception. DATA_SOURCE.md and docs/SCHEMA.md record that the
# pinned revision stores exactly one event at location_x = 120.1, and the WP2.2 boundary audit
# measured that this event is a Shot inside the model cohort. See `effective_location` below.
MEASURED_MAX_SOURCE_X = 120.1

# Floating-point slack for the 120.1 comparison only. 120.1 is not exactly representable, so an
# equality test against it would reject the very value it is meant to admit.
COORDINATE_TOLERANCE = 1e-12


class ShotGeometryError(ValueError):
    """A shot location the geometry contract does not define a value for.

    A ValueError subclass so callers can catch it precisely without the contract having to invent
    a sentinel float. Every raise site names the input and the rule it violated: a location outside
    the contract is a fact about the data worth surfacing, not something to paper over with a
    plausible number.
    """


def effective_location(location_x: float, location_y: float) -> tuple[float, float]:
    """Validate a raw shot location and return the coordinates geometry is computed from.

    Both derived features are defined on this one result, so distance and angle can never end up
    resting on different coordinate bases.

    The x contract has three bands, and only the middle one adjusts anything:

    1. ``raw_x <= 120.0`` — used unchanged.
    2. ``120.0 < raw_x <= 120.1 + 1e-12`` — geometry uses ``effective_x = 120.0``. This is a
       *bounded source-coordinate tolerance adjustment*, not clamping: it is admissible only up to
       the single measured source maximum, it applies to the derived feature alone, and the stored
       ``location_x`` is never rewritten. The pinned cohort has exactly one such row, reported by
       `shot_id` in reports/wp2.2-geometry-evidence.md.
    3. ``raw_x > 120.1 + 1e-12`` — raises. There is no general normalization here. A coordinate
       beyond the measured source maximum means the source is not what this contract was written
       against, and ``min(x, 120)`` would hide exactly that.

    Raises:
        ShotGeometryError: on a non-finite coordinate, a location off the pitch, an x beyond the
            measured source maximum, or a location exactly on a goalpost, where the visible angle
            is mathematically undefined.
    """
    x = float(location_x)
    y = float(location_y)

    if not math.isfinite(x) or not math.isfinite(y):
        raise ShotGeometryError(
            f"shot location must be finite, got ({location_x!r}, {location_y!r})"
        )

    if not 0.0 <= y <= PITCH_WIDTH:
        raise ShotGeometryError(f"location_y {y} is outside the pitch [0.0, {PITCH_WIDTH}]")

    if x < 0.0:
        raise ShotGeometryError(f"location_x {x} is outside the pitch [0.0, {GOAL_LINE_X}]")

    if x <= GOAL_LINE_X:
        effective_x = x
    elif x <= MEASURED_MAX_SOURCE_X + COORDINATE_TOLERANCE:
        effective_x = GOAL_LINE_X
    else:
        raise ShotGeometryError(
            f"location_x {x} exceeds the measured source maximum {MEASURED_MAX_SOURCE_X}; "
            "the bounded tolerance adjustment does not extend past it and no unbounded clamp "
            "is applied"
        )

    # On a post the two post vectors give cross = dot = 0, and Python's atan2(0.0, 0.0) returns
    # 0.0 without complaint. Zero is the answer for a shot that sees no goal at all, so letting it
    # through would report "no visible goal" for a player standing on the goalpost. The cohort has
    # no such row; the guard exists so that a future one cannot pass silently.
    if effective_x == GOAL_LINE_X and y in (LEFT_POST_Y, RIGHT_POST_Y):
        raise ShotGeometryError(
            f"shot location ({x}, {y}) is exactly on a goalpost, where the visible goal angle "
            "is undefined"
        )

    return effective_x, y


def distance_to_goal(location_x: float, location_y: float) -> float:
    """Euclidean distance in metres-as-yards from the shot to the goal centre (120, 40).

    `math.hypot` rather than ``sqrt(dx*dx + dy*dy)``: it is the stdlib's correctly-rounded
    implementation and avoids the intermediate overflow/underflow that squaring introduces.
    """
    effective_x, y = effective_location(location_x, location_y)
    return math.hypot(GOAL_LINE_X - effective_x, y - GOAL_CENTRE_Y)


def visible_goal_angle(location_x: float, location_y: float) -> float:
    """Angle in radians subtended at the shot by the segment between the two goalposts.

    Returns a value in ``[0.0, pi]``:

    - ``0.0`` on the goal line outside the posts, where the goal has no visible width;
    - ``pi`` on the goal line strictly between the posts, where it spans the whole half-plane;
    - strictly between the two everywhere else on the pitch.
    """
    effective_x, y = effective_location(location_x, location_y)

    # Vectors from the shot to each post. Written out rather than pre-simplified so the code reads
    # as the definition it implements, and so the mirrored case y -> 80 - y runs the identical
    # sequence of multiplications with swapped operands.
    to_left_post = (GOAL_LINE_X - effective_x, LEFT_POST_Y - y)
    to_right_post = (GOAL_LINE_X - effective_x, RIGHT_POST_Y - y)

    cross = to_left_post[0] * to_right_post[1] - to_left_post[1] * to_right_post[0]
    dot = to_left_post[0] * to_right_post[0] + to_left_post[1] * to_right_post[1]

    return math.atan2(cross, dot)
