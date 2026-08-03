-- WP2.2 geometry inputs, version 1.
-- Grain: one row per eligible non-penalty Shot event, identical to
-- `backend/sql/wp2_1/01_model_shot_cohort.sql`. Expected row count: 5,606.
--
-- This query deliberately duplicates the WP2.1 predicate set rather than importing it. The
-- duplication is the point: if the two ever diverge, the row-count anchor in
-- `backend/tests/test_wp2_2_geometry_integration.py` fails loudly instead of a geometry report
-- being measured on a quietly different population.
--
-- `is_goal` is NOT projected. Slice A derives two continuous features from coordinates alone and
-- has no use for the target, so the cheapest guarantee that the target cannot leak into a
-- geometry decision is for it never to be read.
WITH core_scope (competition_id, season_id) AS (
    VALUES (43, 3), (55, 43), (43, 106), (55, 282)
)
SELECT
    e.event_id AS shot_id,
    e.match_id,
    e.location_x AS raw_location_x,
    e.location_y AS raw_location_y
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
ORDER BY e.match_id, e.event_index, e.event_id;
