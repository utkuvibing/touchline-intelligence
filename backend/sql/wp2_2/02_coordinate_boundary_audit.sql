-- WP2.2 coordinate boundary audit, version 1.
-- One aggregate row over exactly the WP2.2 geometry-input population.
--
-- Purpose: decide the geometry contract's boundary policy from measurement instead of assumption.
-- Three questions this answers, none of which are safe to guess:
--
--   1. Does any eligible shot sit on or behind the goal line? `atan2` returns a negative angle for
--      x > GOAL_LINE_X, which breaks the angle invariant outright. `DATA_SOURCE.md` records that
--      the pinned revision holds exactly one event at x = 120.1 but does not say what type of
--      event it is, so whether it reaches this population was an open question. This query
--      answered it: the event is a Shot, and it is in the cohort.
--   2. Does any eligible shot sit exactly on a goalpost? There the two post vectors give
--      cross = dot = 0 and Python's atan2(0.0, 0.0) returns 0.0 without complaint -- a silently
--      wrong answer that a guard has to intercept.
--   3. Are coordinates already recorded in the attacking direction? The StatsBomb specification
--      (Appendix 2) documents the pitch and goal coordinates but states nothing about direction of
--      play, so `shots_x_lt_60` is the empirical stand-in: absolute pitch coordinates would put
--      roughly half of all shots in the low-x half.
WITH core_scope (competition_id, season_id) AS (
    VALUES (43, 3), (55, 43), (43, 106), (55, 282)
),
cohort AS (
    SELECT
        e.location_x AS x,
        e.location_y AS y
    FROM shots AS s
    JOIN events AS e USING (event_id)
    JOIN matches AS m USING (match_id)
    JOIN core_scope AS scope USING (competition_id, season_id)
    WHERE e.player_id IS NOT NULL
      AND e.period IS NOT NULL
      AND e.location_x IS NOT NULL
      AND e.location_y IS NOT NULL
      AND s.outcome_name IS NOT NULL
      AND s.body_part_name IS NOT NULL
      AND s.technique_name IS NOT NULL
      AND s.shot_type_name IS NOT NULL
      AND s.shot_type_name <> 'Penalty'
      AND e.period <> 5
)
SELECT
    count(*)                                                       AS cohort_rows,
    min(x)                                                         AS min_x,
    max(x)                                                         AS max_x,
    min(y)                                                         AS min_y,
    max(y)                                                         AS max_y,
    count(*) FILTER (WHERE x IS NULL)                              AS null_x,
    count(*) FILTER (WHERE y IS NULL)                              AS null_y,
    count(*) FILTER (WHERE x > 120.0)                              AS shots_x_gt_120,
    count(*) FILTER (WHERE x >= 120.0)                             AS shots_x_ge_120,
    count(*) FILTER (WHERE x >= 120.1)                             AS shots_x_ge_120_1,
    count(*) FILTER (WHERE x < 60.0)                               AS shots_x_lt_60,
    count(*) FILTER (WHERE x = 120.0 AND y IN (36.0, 44.0))        AS shots_on_post_point,
    count(*) FILTER (
        WHERE (120.0 - x) * (120.0 - x) + (y - 40.0) * (y - 40.0) < 16.0
    )                                                              AS shots_inside_h_circle,
    count(*) FILTER (
        WHERE (120.0 - x) * (120.0 - x) + (y - 40.0) * (y - 40.0) = 16.0
    )                                                              AS shots_on_h_circle
FROM cohort;
