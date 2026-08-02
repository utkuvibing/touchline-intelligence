-- Question: Which players have the largest recorded non-penalty shot and goal volumes?
-- Grain: one row per player; top 25 by shot count.
-- Joins: shots -> events attributes the recorded player; players supplies the current source label.
-- NULLs: events without a player are excluded from a player ranking. Known eligibility fields use
-- the same explicit exclusions as query 05.
-- Interpretation: this is shot volume, not an appearance-normalized or minutes-normalized rate.
SELECT
    p.player_id,
    p.player_name,
    count(*) AS eligible_shots,
    count(*) FILTER (WHERE s.outcome_name = 'Goal') AS goals,
    round(
        100.0 * count(*) FILTER (WHERE s.outcome_name = 'Goal') / nullif(count(*), 0),
        2
    ) AS conversion_pct
FROM shots AS s
JOIN events AS e USING (event_id)
JOIN players AS p USING (player_id)
WHERE s.shot_type_name IS NOT NULL
  AND e.period IS NOT NULL
  AND s.outcome_name IS NOT NULL
  AND s.shot_type_name <> 'Penalty'
  AND e.period <> 5
GROUP BY p.player_id, p.player_name
ORDER BY eligible_shots DESC, goals DESC, p.player_id
LIMIT 25;
