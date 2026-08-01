-- Relationships and source-shape invariants for the shot-focused M1 schema.
-- Display names and source categories deliberately remain open text: they are not stable identifiers.

ALTER TABLE competitions
    ADD CONSTRAINT competitions_id_positive
        CHECK (competition_id > 0 AND season_id > 0),
    ADD CONSTRAINT competitions_names_not_blank
        CHECK (btrim(competition_name) <> '' AND btrim(season_name) <> '');

ALTER TABLE teams
    ADD CONSTRAINT teams_id_positive CHECK (team_id > 0),
    ADD CONSTRAINT teams_name_not_blank CHECK (btrim(team_name) <> '');

ALTER TABLE players
    ADD CONSTRAINT players_id_positive CHECK (player_id > 0),
    ADD CONSTRAINT players_name_not_blank CHECK (btrim(player_name) <> '');

ALTER TABLE matches
    ADD CONSTRAINT matches_competition_fk
        FOREIGN KEY (competition_id, season_id)
        REFERENCES competitions (competition_id, season_id),
    ADD CONSTRAINT matches_home_team_fk
        FOREIGN KEY (home_team_id) REFERENCES teams (team_id),
    ADD CONSTRAINT matches_away_team_fk
        FOREIGN KEY (away_team_id) REFERENCES teams (team_id),
    ADD CONSTRAINT matches_id_positive CHECK (match_id > 0),
    ADD CONSTRAINT matches_distinct_teams CHECK (home_team_id <> away_team_id),
    ADD CONSTRAINT matches_scores_nonnegative
        CHECK (home_score IS NULL OR home_score >= 0),
    ADD CONSTRAINT matches_away_score_nonnegative
        CHECK (away_score IS NULL OR away_score >= 0),
    ADD CONSTRAINT matches_score_pair_complete
        CHECK ((home_score IS NULL) = (away_score IS NULL));

ALTER TABLE shots
    ADD CONSTRAINT shots_match_fk
        FOREIGN KEY (match_id) REFERENCES matches (match_id),
    ADD CONSTRAINT shots_team_fk
        FOREIGN KEY (team_id) REFERENCES teams (team_id),
    ADD CONSTRAINT shots_player_fk
        FOREIGN KEY (player_id) REFERENCES players (player_id),
    ADD CONSTRAINT shots_id_not_blank CHECK (btrim(shot_id) <> ''),
    ADD CONSTRAINT shots_period_valid CHECK (period IS NULL OR period BETWEEN 1 AND 5),
    ADD CONSTRAINT shots_minute_nonnegative CHECK (minute IS NULL OR minute >= 0),
    ADD CONSTRAINT shots_second_valid CHECK (second IS NULL OR second BETWEEN 0 AND 59),
    ADD CONSTRAINT shots_location_pair_complete
        CHECK ((location_x IS NULL) = (location_y IS NULL)),
    ADD CONSTRAINT shots_location_x_bounds
        CHECK (location_x IS NULL OR location_x BETWEEN 0.0 AND 120.0),
    ADD CONSTRAINT shots_location_y_bounds
        CHECK (location_y IS NULL OR location_y BETWEEN 0.0 AND 80.0);
