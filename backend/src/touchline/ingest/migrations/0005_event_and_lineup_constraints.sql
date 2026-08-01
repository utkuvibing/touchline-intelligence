-- Relationship and source-shape guarantees for the normalized/event schema. No secondary indexes
-- are introduced here: query-driven index decisions remain a later work package.

ALTER TABLE competitions
    ADD CONSTRAINT competitions_id_positive CHECK (competition_id > 0),
    ADD CONSTRAINT competitions_name_not_blank CHECK (btrim(competition_name) <> '');

ALTER TABLE seasons
    ADD CONSTRAINT seasons_id_positive CHECK (season_id > 0),
    ADD CONSTRAINT seasons_name_not_blank CHECK (btrim(season_name) <> '');

ALTER TABLE competition_seasons
    ADD CONSTRAINT competition_seasons_competition_fk FOREIGN KEY (competition_id)
        REFERENCES competitions (competition_id),
    ADD CONSTRAINT competition_seasons_season_fk FOREIGN KEY (season_id)
        REFERENCES seasons (season_id);

ALTER TABLE matches
    ADD CONSTRAINT matches_competition_fk FOREIGN KEY (competition_id, season_id)
        REFERENCES competition_seasons (competition_id, season_id);

ALTER TABLE match_teams
    ADD CONSTRAINT match_teams_match_fk FOREIGN KEY (match_id) REFERENCES matches (match_id),
    ADD CONSTRAINT match_teams_team_fk FOREIGN KEY (team_id) REFERENCES teams (team_id),
    ADD CONSTRAINT match_teams_role_valid CHECK (role IN ('home', 'away'));

ALTER TABLE lineups
    ADD CONSTRAINT lineups_match_team_fk FOREIGN KEY (match_id, team_id)
        REFERENCES match_teams (match_id, team_id);

ALTER TABLE lineup_memberships
    ADD CONSTRAINT lineup_memberships_lineup_fk FOREIGN KEY (match_id, team_id)
        REFERENCES lineups (match_id, team_id),
    ADD CONSTRAINT lineup_memberships_player_fk FOREIGN KEY (player_id) REFERENCES players (player_id),
    ADD CONSTRAINT lineup_memberships_jersey_number_positive
        CHECK (jersey_number IS NULL OR jersey_number > 0),
    ADD CONSTRAINT lineup_memberships_player_name_not_blank CHECK (btrim(player_name) <> ''),
    ADD CONSTRAINT lineup_memberships_country_pair_complete
        CHECK ((country_id IS NULL) = (country_name IS NULL));

ALTER TABLE lineup_positions
    ADD CONSTRAINT lineup_positions_membership_fk FOREIGN KEY (match_id, team_id, player_id)
        REFERENCES lineup_memberships (match_id, team_id, player_id),
    ADD CONSTRAINT lineup_positions_period_valid
        CHECK ((from_period IS NULL OR from_period BETWEEN 1 AND 5)
           AND (to_period IS NULL OR to_period BETWEEN 1 AND 5)),
    ADD CONSTRAINT lineup_positions_source_order_positive CHECK (source_order > 0),
    ADD CONSTRAINT lineup_positions_name_pair_complete
        CHECK ((position_id IS NULL) = (position_name IS NULL));
-- The measured source has 17 position records where `to` is earlier than `from`; no chronology
-- check belongs here until that source convention is understood.

ALTER TABLE lineup_cards
    ADD CONSTRAINT lineup_cards_membership_fk FOREIGN KEY (match_id, team_id, player_id)
        REFERENCES lineup_memberships (match_id, team_id, player_id),
    ADD CONSTRAINT lineup_cards_type_not_blank CHECK (btrim(card_type) <> ''),
    ADD CONSTRAINT lineup_cards_period_valid CHECK (period IS NULL OR period BETWEEN 1 AND 5),
    ADD CONSTRAINT lineup_cards_source_order_positive CHECK (source_order > 0);

ALTER TABLE possessions
    ADD CONSTRAINT possessions_match_fk FOREIGN KEY (match_id) REFERENCES matches (match_id),
    ADD CONSTRAINT possessions_match_team_fk FOREIGN KEY (match_id, team_id)
        REFERENCES match_teams (match_id, team_id),
    ADD CONSTRAINT possessions_id_positive CHECK (possession_id > 0);

ALTER TABLE events
    ADD CONSTRAINT events_match_fk FOREIGN KEY (match_id) REFERENCES matches (match_id),
    ADD CONSTRAINT events_match_team_fk FOREIGN KEY (match_id, team_id)
        REFERENCES match_teams (match_id, team_id),
    ADD CONSTRAINT events_player_fk FOREIGN KEY (player_id) REFERENCES players (player_id),
    ADD CONSTRAINT events_possession_fk FOREIGN KEY (match_id, possession_id)
        REFERENCES possessions (match_id, possession_id),
    ADD CONSTRAINT events_index_positive CHECK (event_index IS NULL OR event_index > 0),
    ADD CONSTRAINT events_match_index_unique UNIQUE (match_id, event_index),
    ADD CONSTRAINT events_id_type_unique UNIQUE (event_id, event_type_name),
    ADD CONSTRAINT events_period_valid CHECK (period IS NULL OR period BETWEEN 1 AND 5),
    ADD CONSTRAINT events_minute_nonnegative CHECK (minute IS NULL OR minute >= 0),
    ADD CONSTRAINT events_second_valid CHECK (second IS NULL OR second BETWEEN 0 AND 59),
    ADD CONSTRAINT events_duration_nonnegative CHECK (duration IS NULL OR duration >= 0),
    ADD CONSTRAINT events_location_pair_complete CHECK ((location_x IS NULL) = (location_y IS NULL)),
    ADD CONSTRAINT events_location_x_bounds CHECK (location_x IS NULL OR location_x BETWEEN 0.0 AND 120.0),
    ADD CONSTRAINT events_location_y_bounds CHECK (location_y IS NULL OR location_y BETWEEN 0.0 AND 80.0),
    ADD CONSTRAINT events_type_name_not_blank CHECK (btrim(event_type_name) <> ''),
    ADD CONSTRAINT events_type_data_object
        CHECK (type_data IS NULL OR jsonb_typeof(type_data) = 'object'),
    ADD CONSTRAINT events_shots_have_no_residual_details
        CHECK (event_type_name <> 'Shot' OR type_data IS NULL),
    ADD CONSTRAINT events_no_provider_xg
        CHECK (type_data IS NULL OR NOT jsonb_path_exists(type_data, '$.**.statsbomb_xg'));

ALTER TABLE event_relations
    ADD CONSTRAINT event_relations_source_event_fk FOREIGN KEY (match_id, source_event_id)
        REFERENCES events (match_id, event_id),
    ADD CONSTRAINT event_relations_related_event_fk FOREIGN KEY (match_id, related_event_id)
        REFERENCES events (match_id, event_id),
    ADD CONSTRAINT event_relations_not_self CHECK (source_event_id <> related_event_id),
    ADD CONSTRAINT event_relations_source_order_positive CHECK (source_order > 0),
    ADD CONSTRAINT event_relations_source_order_unique UNIQUE (source_event_id, source_order);

ALTER TABLE shots
    DROP CONSTRAINT shots_match_fk,
    DROP CONSTRAINT shots_team_fk,
    DROP CONSTRAINT shots_player_fk,
    DROP CONSTRAINT shots_id_not_blank,
    DROP CONSTRAINT shots_period_valid,
    DROP CONSTRAINT shots_minute_nonnegative,
    DROP CONSTRAINT shots_second_valid,
    DROP CONSTRAINT shots_location_pair_complete,
    DROP CONSTRAINT shots_location_x_bounds,
    DROP CONSTRAINT shots_location_y_bounds,
    DROP CONSTRAINT shots_pkey,
    DROP COLUMN shot_id,
    DROP COLUMN match_id,
    DROP COLUMN team_id,
    DROP COLUMN player_id,
    DROP COLUMN period,
    DROP COLUMN minute,
    DROP COLUMN second,
    DROP COLUMN location_x,
    DROP COLUMN location_y,
    DROP COLUMN outcome,
    DROP COLUMN body_part,
    DROP COLUMN technique,
    DROP COLUMN shot_type,
    ALTER COLUMN event_id SET NOT NULL,
    ADD COLUMN event_type_name text NOT NULL DEFAULT 'Shot',
    ADD CONSTRAINT shots_pkey PRIMARY KEY (event_id),
    ADD CONSTRAINT shots_event_type_is_shot CHECK (event_type_name = 'Shot'),
    ADD CONSTRAINT shots_event_fk FOREIGN KEY (event_id, event_type_name)
        REFERENCES events (event_id, event_type_name),
    ADD CONSTRAINT shots_end_location_pair_complete
        CHECK ((end_location_x IS NULL) = (end_location_y IS NULL)),
    ADD CONSTRAINT shots_end_location_x_bounds
        CHECK (end_location_x IS NULL OR end_location_x BETWEEN 0.0 AND 120.0),
    ADD CONSTRAINT shots_end_location_y_bounds
        CHECK (end_location_y IS NULL OR end_location_y BETWEEN 0.0 AND 80.0),
    ADD CONSTRAINT shots_end_location_z_nonnegative
        CHECK (end_location_z IS NULL OR end_location_z >= 0),
    ADD CONSTRAINT shots_key_pass_event_fk FOREIGN KEY (key_pass_event_id)
        REFERENCES events (event_id);

ALTER TABLE shot_freeze_frame_players
    ADD CONSTRAINT shot_freeze_frame_players_shot_fk FOREIGN KEY (event_id)
        REFERENCES shots (event_id),
    ADD CONSTRAINT shot_freeze_frame_players_player_fk FOREIGN KEY (player_id)
        REFERENCES players (player_id),
    ADD CONSTRAINT shot_freeze_frame_players_source_order_positive CHECK (source_order > 0),
    ADD CONSTRAINT shot_freeze_frame_players_position_name_pair_complete
        CHECK ((position_id IS NULL) = (position_name IS NULL)),
    ADD CONSTRAINT shot_freeze_frame_players_location_pair_complete
        CHECK ((location_x IS NULL) = (location_y IS NULL)),
    ADD CONSTRAINT shot_freeze_frame_players_location_x_bounds
        CHECK (location_x IS NULL OR location_x BETWEEN 0.0 AND 120.0),
    ADD CONSTRAINT shot_freeze_frame_players_location_y_bounds
        CHECK (location_y IS NULL OR location_y BETWEEN 0.0 AND 80.0);
