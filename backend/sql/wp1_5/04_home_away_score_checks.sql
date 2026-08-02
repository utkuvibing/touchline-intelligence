-- Question: Do normalized match-team roles agree with the match's home/away foreign keys, and are
-- score pairs complete?
-- Grain: one row for the full loaded cohort (a diagnostic summary, not a repair).
-- Joins: correlated EXISTS checks test the exact match-team identity and role without multiplying.
-- NULLs: XOR detects an incomplete score pair; both NULL is counted separately as unknown.
SELECT
    count(*) AS match_count,
    count(*) FILTER (
        WHERE NOT EXISTS (
            SELECT 1
            FROM match_teams AS mt
            WHERE mt.match_id = m.match_id
              AND mt.team_id = m.home_team_id
              AND mt.role = 'home'
        )
    ) AS missing_home_role,
    count(*) FILTER (
        WHERE NOT EXISTS (
            SELECT 1
            FROM match_teams AS mt
            WHERE mt.match_id = m.match_id
              AND mt.team_id = m.away_team_id
              AND mt.role = 'away'
        )
    ) AS missing_away_role,
    count(*) FILTER (
        WHERE (m.home_score IS NULL) <> (m.away_score IS NULL)
    ) AS incomplete_score_pairs,
    count(*) FILTER (
        WHERE m.home_score IS NULL AND m.away_score IS NULL
    ) AS matches_without_score
FROM matches AS m;
