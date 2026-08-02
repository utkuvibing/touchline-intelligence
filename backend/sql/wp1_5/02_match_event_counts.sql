-- Question: How many recorded possessions, events, and shots does each match contain?
-- Grain: one row per match.
-- Joins: each child table is aggregated independently before joining, so events do not multiply
-- possessions or shots. Team labels come from the explicit home/away match foreign keys.
-- NULLs: LEFT JOIN plus COALESCE retains a match with no child rows as zero coverage.
WITH event_counts AS (
    SELECT
        e.match_id,
        count(*) AS event_count,
        count(s.event_id) AS shot_count
    FROM events AS e
    LEFT JOIN shots AS s USING (event_id)
    GROUP BY e.match_id
), possession_counts AS (
    SELECT match_id, count(*) AS possession_count
    FROM possessions
    GROUP BY match_id
)
SELECT
    m.match_id,
    m.match_date,
    home.team_name AS home_team,
    away.team_name AS away_team,
    m.home_score,
    m.away_score,
    coalesce(pc.possession_count, 0) AS possession_count,
    coalesce(ec.event_count, 0) AS event_count,
    coalesce(ec.shot_count, 0) AS shot_count
FROM matches AS m
JOIN teams AS home ON home.team_id = m.home_team_id
JOIN teams AS away ON away.team_id = m.away_team_id
LEFT JOIN possession_counts AS pc USING (match_id)
LEFT JOIN event_counts AS ec USING (match_id)
ORDER BY m.match_date, m.match_id;
