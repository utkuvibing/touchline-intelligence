-- WP2.3 split population, version 1.
-- Grain: one row per ingested match in the locked four-tournament core scope.
-- Target-free: this query reads and projects no outcome and no shot-level field.
--
-- `eligible_shots` counts the Shot rows that satisfy WP2.1's cohort predicate set, duplicated
-- verbatim below rather than imported: if the two ever diverge, the 230-row / 5,606-shot anchors
-- in the WP2.3 tests fail loudly instead of the split being locked on a quietly different
-- population. Matches with zero eligible shots are included (the split is a match-level object).
--
-- Expected row count: 230.
WITH core_scope (competition_id, season_id) AS (
    VALUES (43, 3), (55, 43), (43, 106), (55, 282)
),
eligible_shots AS (
    SELECT e.match_id, e.event_id
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
    m.match_id,
    m.competition_id,
    m.season_id,
    m.match_date,
    count(es.event_id)::int AS eligible_shots
FROM matches AS m
JOIN core_scope AS scope USING (competition_id, season_id)
LEFT JOIN eligible_shots AS es USING (match_id)
GROUP BY m.match_id, m.competition_id, m.season_id, m.match_date
ORDER BY m.match_date, m.match_id;
