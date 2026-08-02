-- WP2.1 tournament-level penalty reconciliation.
-- Grain: one row per loaded declared competition-season.
-- Penalties remain outside the primary model cohort but visible as reproducible source evidence.
WITH core_scope (competition_id, season_id) AS (
    VALUES (43, 3), (55, 43), (43, 106), (55, 282)
)
SELECT
    m.competition_id,
    m.season_id,
    c.competition_name,
    se.season_name,
    count(*) FILTER (
        WHERE s.shot_type_name = 'Penalty' AND e.period <> 5
    ) AS regulation_penalties,
    count(*) FILTER (
        WHERE s.shot_type_name = 'Penalty' AND e.period = 5
    ) AS shootout_penalties,
    count(*) FILTER (
        WHERE s.shot_type_name <> 'Penalty' AND e.period = 5
    ) AS period_five_non_penalties
FROM core_scope AS scope
JOIN matches AS m USING (competition_id, season_id)
JOIN competitions AS c USING (competition_id)
JOIN seasons AS se USING (season_id)
LEFT JOIN events AS e USING (match_id)
LEFT JOIN shots AS s USING (event_id)
GROUP BY m.competition_id, m.season_id, c.competition_name, se.season_name
ORDER BY min(m.match_date), m.competition_id, m.season_id;
