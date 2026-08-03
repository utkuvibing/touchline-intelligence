# WP2.2 Slice A geometry evidence

Measured 2026-08-03 against the local full-cohort PostgreSQL state for pinned StatsBomb Open Data
commit `b0bc9f22dd77c206ddedc1d742893b3bbe64baec`. Every query ran read-only, in a `READ ONLY`
transaction; no migration, insert, update, delete or seed was executed. The deployed database was
not queried.

This is descriptive geometry evidence. No split was created, no model was fitted, and no target
column was read.

Reproduce against a local database that has been migrated and ingested:

```bash
TOUCHLINE_FULL_COHORT_DB_URL='postgresql://touchline:localdev@localhost:5433/touchline' \
    uv run pytest backend/tests/test_wp2_2_geometry_integration.py -m full_cohort
```

GitHub Actions does **not** run these tests. Its PostgreSQL service container is empty by design —
CI never downloads or ingests the StatsBomb dataset — so `TOUCHLINE_FULL_COHORT_DB_URL` is unset
there and the module skips with that reason stated. The numbers below come from a local run.

## Population

`backend/sql/wp2_2/01_geometry_inputs.sql` returned **5,606 rows**, matching WP2.1's locked
non-penalty cohort exactly. The WP2.2 query duplicates WP2.1's predicate set rather than importing
it, so divergence surfaces as a failed row-count anchor rather than as a report measured on a
quietly different population.

## Boundary audit

`backend/sql/wp2_2/02_coordinate_boundary_audit.sql`:

| Measure | Value |
|---|---:|
| `cohort_rows` | 5,606 |
| `min_x` / `max_x` | 48.1 / 120.1 |
| `min_y` / `max_y` | 0.7 / 79.3 |
| `null_x` / `null_y` | 0 / 0 |
| `shots_x_gt_120` | 1 |
| `shots_x_ge_120` | 3 |
| `shots_x_ge_120_1` | 1 |
| `shots_x_lt_60` | 9 |
| `shots_on_post_point` | 0 |
| `shots_inside_h_circle` | 38 |
| `shots_on_h_circle` | 1 |

## Derived feature distributions

Computed by `touchline.features.geometry` over all 5,606 rows. No NaN, no infinity, no
out-of-domain value.

| Feature | min | p05 | median | mean | p95 | max |
|---|---:|---:|---:|---:|---:|---:|
| `distance_to_goal` (yards) | 0.7616 | 6.7936 | 18.2681 | 18.8162 | 32.6267 | 72.3327 |
| `visible_goal_angle` (rad) | 0.0000 | 0.1958 | 0.3460 | 0.4486 | 1.0197 | 2.7932 |

Median visible angle 19.83°, mean 25.70°. Three rows have `angle = 0` exactly — the three shots
recorded on the goal line, all outside the posts. No row has `distance = 0` and no row reaches
`angle = pi`; the goalmouth interior is unoccupied in this cohort.

## The single bounded source-coordinate tolerance adjustment

Exactly **one** row of 5,606 received an adjusted coordinate:

| Field | Value |
|---|---|
| `shot_id` | `78116cc8-afbe-4bae-975b-57ce6983d045` |
| Match | `3938638`, Euro 2024 `(55, 282)`, 2024-06-17, Romania |
| Player | Nicolae Claudiu Stanciu |
| Clock | period 1, 38:43 |
| Shot type / body part / technique / outcome | Corner / Right Foot / Normal / Post |
| **Raw coordinates** | **(120.1, 0.8)** |
| **Effective coordinates for geometry** | **(120.0, 0.8)** |
| `distance_to_goal` | 39.2 |
| `visible_goal_angle` | 0.0 |

This is the same event `DATA_SOURCE.md` records as the pinned revision's measured event-coordinate
exception. That document states the coordinate and identifies the event, but does not say what type
of event it is; whether it reached the shot cohort was open until this audit measured it. Its shot
type is `Corner`, so the recorded location is the corner arc where the goal line meets the
touchline; the 0.1 places it fractionally behind the goal line.

**The StatsBomb source data is not modified by this decision.** `events.location_x` still stores
`120.1`, the ingestion contract and the `0.0 <= location_x <= 120.1` database constraint are
unchanged, and `01_geometry_inputs.sql` projects the raw value. The adjustment exists only inside
`touchline.features.geometry.effective_location` and applies only to the derived distance and
angle. It is bounded by the measured source maximum: a coordinate beyond `120.1 + 1e-12` raises
`ShotGeometryError` rather than being clamped.

Without the adjustment this row yields `atan2(-0.80, 1520.65) = -0.00052609 rad` — a negative
visible angle, breaking the `0 <= angle <= pi` invariant. The adjusted value is `0.0`: from the
corner flag the goal subtends no visible width, which is the same physical statement the raw
coordinate makes to within its own measurement noise.

The other two `x >= 120` rows are at `x = 120.0` exactly and need no adjustment. Both fall under
the pre-existing goal-line-outside-the-posts rule and return `angle = 0.0`:

| `shot_id` | Match | Raw coordinates |
|---|---|---|
| `2df12147-20e3-409f-82da-ea198b3bd365` | `3857261`, WC 2022, Harry Maguire | (120.0, 54.6) |
| `419bacaf-e136-4583-9d03-aa057311fb8e` | `3930168`, Euro 2024, Barnabás Varga | (120.0, 34.2) |

## Attacking direction

The StatsBomb Open Data Specification v1.1 documents the pitch and goal coordinates in Appendix 2
but states nothing about direction of play, so this is established empirically rather than cited.

Nine shots of 5,606 (0.16%) sit below the halfway line, and the minimum recorded `location_x` is
48.1 — no shot in the cohort is even in its own defensive third. Absolute pitch coordinates would
place roughly half the shots below `x = 60`. The measurement is consistent with coordinates already
recorded in the attacking direction, so Slice A applies **no** direction transform. This is a
documented no-op, not a skipped step.

## Numerical stability, measured

The classic single-arctangent form for the visible angle fails wherever
`a^2 + c^2 - h^2 <= 0` — the disc of radius 4 around the goal centre. That region is populated:

- **38 shots** lie strictly inside it, where the naive form returns a *negative* angle for a shot
  that in fact sees an obtuse slice of goal;
- **1 shot** lies exactly on its boundary, where the naive form divides by zero.

39 real rows, not a theoretical corner. `backend/tests/test_wp2_2_geometry.py` pins the failure at
(118, 40): both forms compute the same `cross = 16` and `dot = -12`, and the naive form returns
`-0.9273 rad` where the two-post form returns `2.2143 rad`.

## Scope

Slice A ships geometry only. Categorical and context features, coverage and semantics decisions for
the WP2.1 `Uncertain` fields, training-only preprocessing, and the training/serving feature contract
are Slice B and are not addressed here. No split, model, calibration or performance claim exists at
this point.

Data provided by StatsBomb.
