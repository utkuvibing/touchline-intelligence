-- Question: What are each team's recorded match results within each competition-season?
-- Grain: one row per competition-season and team.
-- Joins: UNION ALL deliberately turns every match into exactly two team-perspective rows.
-- NULLs: matches with an absent score remain in match_count but not matches_with_score, W/D/L,
-- goals, goal difference, or points; zero is not substituted for an unknown score.
WITH team_matches AS (
    SELECT
        competition_id,
        season_id,
        match_id,
        home_team_id AS team_id,
        home_score AS goals_for,
        away_score AS goals_against
    FROM matches
    UNION ALL
    SELECT
        competition_id,
        season_id,
        match_id,
        away_team_id AS team_id,
        away_score AS goals_for,
        home_score AS goals_against
    FROM matches
)
SELECT
    c.competition_name,
    se.season_name,
    t.team_name,
    count(*) AS match_count,
    count(*) FILTER (WHERE tm.goals_for IS NOT NULL) AS matches_with_score,
    count(*) FILTER (WHERE tm.goals_for > tm.goals_against) AS wins,
    count(*) FILTER (WHERE tm.goals_for = tm.goals_against) AS draws,
    count(*) FILTER (WHERE tm.goals_for < tm.goals_against) AS losses,
    sum(tm.goals_for) AS goals_for,
    sum(tm.goals_against) AS goals_against,
    sum(tm.goals_for - tm.goals_against) AS goal_difference,
    sum(
        CASE
            WHEN tm.goals_for IS NULL THEN NULL
            WHEN tm.goals_for > tm.goals_against THEN 3
            WHEN tm.goals_for = tm.goals_against THEN 1
            ELSE 0
        END
    ) AS points
FROM team_matches AS tm
JOIN competitions AS c USING (competition_id)
JOIN seasons AS se USING (season_id)
JOIN teams AS t USING (team_id)
GROUP BY tm.competition_id, tm.season_id, c.competition_name, se.season_name, tm.team_id, t.team_name
ORDER BY tm.competition_id, tm.season_id, points DESC NULLS LAST, t.team_name;
