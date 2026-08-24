# WP2.2 Slice A geometry contract

Slice A of WP2.2 defines two continuous shot features and nothing else. It creates no split, fits
nothing, reads no target, and makes no performance claim. Slice B — categorical and context
features, coverage and semantics decisions for WP2.1's `Uncertain` fields, training-only
preprocessing, and the training/serving feature contract — is not covered here.

Measured evidence: [`reports/wp2.2-geometry-evidence.md`](../../reports/wp2.2-geometry-evidence.md).

## Pitch and goal constants

Source: **StatsBomb Open Data Specification v1.1, Appendix 2 "Locations"**, in the `doc/` directory
of the pinned Open Data repository. Checked 2026-08-03.

Appendix 2 carries these values as diagrams rather than prose, which is why they are recorded here
instead of being left implicit in the formulas:

| Constant | Value | Where in the specification |
|---|---:|---|
| `PITCH_LENGTH` | 120.0 | p.35, pitch drawn (0,0)–(120,80) |
| `PITCH_WIDTH` | 80.0 | p.35 |
| `GOAL_LINE_X` | 120.0 | p.36, goalmouth corners labelled `120, 36, 0` and `120, 44, 0` |
| `LEFT_POST_Y` | 36.0 | p.36 |
| `RIGHT_POST_Y` | 44.0 | p.36 |
| `GOAL_CENTRE_Y` | 40.0 | derived; p.35 also labels the centre spot `60,40` |
| `GOAL_WIDTH` | 8.0 | derived from the two posts |
| `CROSSBAR_Z` | 2.67 | p.36, upper corners `120, 36, 2.67` and `120, 44, 2.67` |

The body text corroborates the scale independently: the `location` field description gives "the
center of the field is (60,40)", and the shot `end_location` examples are `(120, 50)` and
`(120, 32.5, 1.2)`. p.35 also labels the penalty spot `108,40`, which is the hand-computed test
case in `backend/tests/test_wp2_2_geometry.py`.

Slice A is two-dimensional. `CROSSBAR_Z` is recorded for completeness and never read.

## Features

Both are pure functions of one recorded shot location, in `touchline.features.geometry`.

**`distance_to_goal(x, y)`** — Euclidean distance in StatsBomb coordinate units to the goal centre
`(120, 40)`, via `math.hypot` rather than `sqrt(dx*dx + dy*dy)`: the stdlib implementation is
correctly rounded and avoids the intermediate overflow and underflow that squaring introduces. The
source contract does not guarantee yards, metres, or another physical unit, so no such unit is
claimed.

**`visible_goal_angle(x, y)`** — the angle subtended at the shot by the segment between the posts,
in radians.

### Why the two-post form

With `a = 120 - x`, `c = y - 40`, `h = 4`, the classic single-arctangent expression is

```
atan((GOAL_WIDTH * a) / (a**2 + c**2 - h**2))
```

Expanding the two post vectors `p1 = (a, 36 - y)` and `p2 = (a, 44 - y)` shows that its numerator
is exactly `cross(p1, p2) = 8a` and its denominator exactly `dot(p1, p2) = a**2 + c**2 - h**2`.
So the naive form is `atan(cross / dot)` and the implemented form is `atan2(cross, dot)`. **The
entire difference is that dividing discards the sign of the denominator, and with it the quadrant.**

For `a > 0`:

| Condition | Naive versus stable |
|---|---|
| `dot > 0` | identical |
| `dot = 0` | naive raises `ZeroDivisionError`; stable returns `pi/2` |
| `dot < 0` | naive returns a **negative** angle; `stable - naive = pi` exactly |

`dot < 0` is the disc of radius `h` around the goal centre. The pinned cohort has **38 shots**
strictly inside it and **1 exactly on its boundary** — 39 real rows where the naive form is wrong
or raises. The stability argument is measured, not asserted.

This relation is stated for `a > 0` only. At `a = 0` the naive form returns negative zero rather
than a negative number, and for `a < 0` the difference is `-pi`; both are handled as boundary cases
below rather than folded into the general rule.

The naive form is not implemented in production code. It lives in the test module as a reference
implementation whose only job is to make the failure reproducible.

## Angle invariant, stated per domain

Not one blanket rule — a blanket `0 <= angle <= pi` would pass while hiding a goal-line row that
answered the wrong one of the two boundary cases.

| Domain | Contract |
|---|---|
| `effective_x < 120` | `0 < angle < pi`, both bounds strictly excluded |
| `effective_x = 120`, `36 < y < 44` | `angle = pi` — the goal spans the half-plane |
| `effective_x = 120`, `y < 36` or `y > 44` | `angle = 0` — no visible width |
| `effective_x = 120`, `y in {36, 44}` | undefined; raises `ShotGeometryError` |

The post case is a guard, not a formality: there both post vectors give `cross = dot = 0`, and
Python's `atan2(0.0, 0.0)` returns `0.0` without complaint. Zero is also the honest answer for a
shot that sees no goal at all, so letting it through would report "no visible goal" for a player
standing on the goalpost. The cohort contains no such row; the guard exists so a future one cannot
pass silently.

## Bounded source-coordinate tolerance adjustment

This is **not** general clamping. It is a bounded, auditable derived-feature policy for one
measured source exception, and it is stated in three bands:

| Band | Behaviour |
|---|---|
| `raw_x <= 120.0` | coordinate used unchanged |
| `120.0 < raw_x <= 120.1 + 1e-12` | geometry uses `effective_x = 120.0` |
| `raw_x > 120.1 + 1e-12` | raises `ShotGeometryError` |

Three properties make it auditable rather than a silent normalization:

1. **It is bounded by measurement.** `120.1` is the maximum `location_x` the pinned revision
   contains, recorded in `DATA_SOURCE.md` and `docs/SCHEMA.md` and re-measured by the WP2.2
   boundary audit. Past that bound the function raises: there is no `min(x, 120)` anywhere. A
   coordinate beyond the measured maximum means the source is not what this contract was written
   against, and clamping would hide exactly that.
2. **It never touches the source.** `events.location_x` still stores `120.1`, the database
   constraint is unchanged, and `01_geometry_inputs.sql` projects the raw value. The adjustment
   exists only inside `effective_location`.
3. **Both features share it.** `distance_to_goal` and `visible_goal_angle` are defined on the same
   `effective_location` result, so the two can never rest on different coordinate bases.

The tolerance `1e-12` exists because `120.1` is not exactly representable in binary floating point;
an equality test against it would reject the very value it is meant to admit.

**Exactly one row in 5,606 is affected**: shot `78116cc8-afbe-4bae-975b-57ce6983d045`, Euro 2024
Romania–Ukraine, a `Corner` shot recorded at `(120.1, 0.8)` — the corner arc, where the goal line
meets the touchline. Raw `(120.1, 0.8)` becomes effective `(120.0, 0.8)`, giving distance `39.2`
and angle `0.0`. Unadjusted it would yield `-0.00052609 rad`, a negative angle. The adjusted value
says the goal subtends no visible width from the corner flag, which is the same physical statement
the raw coordinate makes to within its own measurement noise.

## Attacking direction

The specification documents the pitch and goal coordinates but **states nothing about direction of
play**. Searches of the specification text for direction-of-play wording return nothing, so this is
established empirically and labelled as such rather than cited.

Nine shots of 5,606 (0.16%) sit below the halfway line and the minimum `location_x` is 48.1 — no
shot is in its own defensive third. Absolute pitch coordinates would put roughly half the cohort
below `x = 60`. Slice A therefore applies **no** direction transform: a documented no-op, not a
skipped step. If a future source pins differently, the audit's `shots_x_lt_60` is where it shows.

## Mirror symmetry

Two claims of different strength, kept apart deliberately:

- **The contract** is mathematical: `f(x, y)` and `f(x, 80 - y)` agree within
  `abs_tol=1e-12`, `rel_tol=0.0`.
- **An implementation anchor** additionally asserts bit equality on four exactly-representable
  integer cases. Mathematical symmetry does not require IEEE-754 bit equality; it holds here only
  because the current implementation runs the mirrored case through the same multiplications with
  commuted operands. If a refactor breaks the anchor while the contract still passes, that is a
  change in arithmetic ordering, not a geometry bug — update the anchor, never the contract.

## Open questions handed to Slice B

- Categorical and context features: body part, technique, play pattern, shot type, and the WP2.1
  `Uncertain` fields (`under_pressure`, `first_time`, `open_goal`, `one_on_one`, `aerial_won`,
  `follows_dribble`), each gated on coverage and absent-versus-false semantics.
- Preprocessing fitted on training rows only.
- The training/serving feature contract and its versioning.
- Whether `distance_to_goal` and `visible_goal_angle` enter a model raw, transformed, or
  interacted — a WP2.4 modelling decision, not a geometry one.

Data provided by StatsBomb.
