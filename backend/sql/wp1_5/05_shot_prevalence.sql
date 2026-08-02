-- Question: What is the observed non-penalty shot conversion prevalence by tournament?
-- Grain: one row per competition-season.
-- Joins: shots -> events supplies recorded context; events -> matches supplies tournament identity.
-- NULLs: unknown shot type, period, or outcome are explicitly excluded from both numerator and
-- denominator. Period 5 and Penalty are excluded by the accepted cohort policy.
-- Interpretation: descriptive prevalence only; not a model, prediction, or M2 evaluation baseline.
SELECT
    c.competition_name,
    se.season_name,
    count(*) AS eligible_shots,
    count(*) FILTER (WHERE s.outcome_name = 'Goal') AS goals,
    round(
        100.0 * count(*) FILTER (WHERE s.outcome_name = 'Goal') / nullif(count(*), 0),
        2
    ) AS conversion_pct
FROM shots AS s
JOIN events AS e USING (event_id)
JOIN matches AS m USING (match_id)
JOIN competitions AS c USING (competition_id)
JOIN seasons AS se USING (season_id)
WHERE s.shot_type_name IS NOT NULL
  AND e.period IS NOT NULL
  AND s.outcome_name IS NOT NULL
  AND s.shot_type_name <> 'Penalty'
  AND e.period <> 5
GROUP BY m.competition_id, m.season_id, c.competition_name, se.season_name
ORDER BY min(m.match_date), c.competition_name;
