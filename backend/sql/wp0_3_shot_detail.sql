-- WP0.3 verification query.
--
-- Returns every shot with its location, the player who took it, both teams, and the outcome —
-- the join that proves the five tables actually connect and that source identifiers were kept.
--
-- Run:  docker exec -i touchline-postgres psql -U touchline -d touchline -f - < backend/sql/wp0_3_shot_detail.sql
--
-- Note the LEFT JOIN on players: a shot can have no attributed player, and an INNER JOIN here
-- would silently drop those rows and change the shot count away from the source. In WC 2022 that
-- set happens to be empty, but the join must not depend on that.

SELECT
    s.shot_id,
    m.match_date,
    m.competition_stage,
    shooting.team_name        AS shooting_team,
    opponent.team_name        AS opponent_team,
    p.player_name,
    s.period,
    s.minute,
    s.second,
    s.location_x,
    s.location_y,
    s.shot_type,
    s.body_part,
    s.technique,
    s.outcome
FROM shots       AS s
JOIN matches     AS m        ON m.match_id = s.match_id
JOIN teams       AS shooting ON shooting.team_id = s.team_id
JOIN teams       AS opponent
     ON opponent.team_id = CASE
            WHEN s.team_id = m.home_team_id THEN m.away_team_id
            ELSE m.home_team_id
        END
LEFT JOIN players AS p       ON p.player_id = s.player_id
ORDER BY m.match_date, s.match_id, s.period, s.minute, s.second;
