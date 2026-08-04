-- WP2.3 shot membership, version 1.
-- Grain: one row per eligible non-penalty Shot event, identical to
-- `backend/sql/wp2_1/01_model_shot_cohort.sql` in population.
-- Target access: this query never projects or inspects the target; `shot_id` is
-- `events.event_id` (the `shots` primary key), aliased per WP2.1 convention. It duplicates
-- WP2.1's eligibility predicate set verbatim, and the inherited `s.outcome_name IS NOT NULL`
-- check is the only place it touches outcome data.
--
-- This query powers the shot-level partition proof: every one of the 5,606 eligible shot ids
-- must join to exactly one match assignment and exactly one top-level split, with no duplicates
-- and no unassigned shots. The predicate set is duplicated verbatim from WP2.1 rather than
-- imported, so a divergence fails the set-equality anchor against the WP2.1 cohort query instead
-- of silently re-scoping the proof.
--
-- Expected row count: 5,606.
WITH core_scope (competition_id, season_id) AS (
    VALUES (43, 3), (55, 43), (43, 106), (55, 282)
)
SELECT
    e.event_id AS shot_id,
    e.match_id
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
ORDER BY m.match_date, e.match_id, e.event_index, e.event_id;
