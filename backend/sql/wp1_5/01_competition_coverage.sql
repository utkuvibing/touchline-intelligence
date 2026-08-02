-- Question: What source coverage is loaded for each competition-season?
-- Grain: one row per competition-season.
-- Joins: events and shots are first reduced to match grain; this prevents a many-to-many
-- multiplication when the match aggregates are combined. Team counts use a UNION of home and away.
-- NULLs: MIN/MAX ignore individual NULL dates and return NULL only when a group has no known date.
-- Counts use LEFT JOIN plus COALESCE so an empty declared competition-season reports zero coverage.
WITH match_facts AS (
    SELECT
        m.match_id,
        m.competition_id,
        m.season_id,
        m.match_date,
        count(e.event_id) AS event_count,
        count(s.event_id) AS shot_count
    FROM matches AS m
    LEFT JOIN events AS e USING (match_id)
    LEFT JOIN shots AS s USING (event_id)
    GROUP BY m.match_id
), competition_teams AS (
    SELECT competition_id, season_id, home_team_id AS team_id FROM matches
    UNION
    SELECT competition_id, season_id, away_team_id AS team_id FROM matches
), team_counts AS (
    SELECT competition_id, season_id, count(*) AS team_count
    FROM competition_teams
    GROUP BY competition_id, season_id
)
SELECT
    c.competition_name,
    se.season_name,
    count(mf.match_id) AS match_count,
    coalesce(tc.team_count, 0) AS team_count,
    min(mf.match_date) AS first_match_date,
    max(mf.match_date) AS last_match_date,
    coalesce(sum(mf.event_count), 0) AS event_count,
    coalesce(sum(mf.shot_count), 0) AS shot_count
FROM competition_seasons AS cs
JOIN competitions AS c USING (competition_id)
JOIN seasons AS se USING (season_id)
LEFT JOIN match_facts AS mf USING (competition_id, season_id)
LEFT JOIN team_counts AS tc USING (competition_id, season_id)
GROUP BY cs.competition_id, cs.season_id, c.competition_name, se.season_name, tc.team_count
ORDER BY min(mf.match_date), c.competition_name;
