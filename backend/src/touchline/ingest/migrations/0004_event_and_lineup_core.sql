-- Core source-shaped entities. UUIDs are reserved for StatsBomb event identifiers; source
-- match, competition, team, player and possession identifiers remain their supplied integers.

CREATE TABLE lineups (
    match_id integer NOT NULL,
    team_id  integer NOT NULL,
    PRIMARY KEY (match_id, team_id)
);

CREATE TABLE lineup_memberships (
    match_id  integer NOT NULL,
    team_id   integer NOT NULL,
    player_id integer NOT NULL,
    jersey_number integer,
    player_name text NOT NULL,
    player_nickname text,
    country_id integer,
    country_name text,
    PRIMARY KEY (match_id, team_id, player_id)
);

CREATE TABLE lineup_positions (
    lineup_position_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    match_id integer NOT NULL,
    team_id integer NOT NULL,
    player_id integer NOT NULL,
    source_order integer NOT NULL,
    position_id integer,
    position_name text,
    from_period integer,
    from_time interval,
    to_period integer,
    to_time interval,
    start_reason text,
    end_reason text,
    UNIQUE (match_id, team_id, player_id, source_order)
);

CREATE TABLE lineup_cards (
    lineup_card_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    match_id integer NOT NULL,
    team_id integer NOT NULL,
    player_id integer NOT NULL,
    source_order integer NOT NULL,
    card_type text NOT NULL,
    reason text,
    period integer,
    time interval,
    UNIQUE (match_id, team_id, player_id, source_order)
);

CREATE TABLE possessions (
    match_id integer NOT NULL,
    possession_id integer NOT NULL,
    team_id integer,
    PRIMARY KEY (match_id, possession_id)
);

CREATE TABLE events (
    event_id uuid PRIMARY KEY,
    match_id integer NOT NULL,
    event_index integer,
    period integer,
    timestamp interval,
    minute integer,
    second integer,
    team_id integer,
    player_id integer,
    possession_id integer,
    under_pressure boolean,
    off_camera boolean,
    out boolean,
    counterpress boolean,
    play_pattern_id integer,
    play_pattern_name text,
    position_id integer,
    position_name text,
    duration double precision,
    location_x double precision,
    location_y double precision,
    event_type_id integer,
    event_type_name text NOT NULL,
    type_data jsonb,
    UNIQUE (match_id, event_id)
);

CREATE TABLE event_relations (
    match_id integer NOT NULL,
    source_event_id uuid NOT NULL,
    related_event_id uuid NOT NULL,
    source_order integer NOT NULL,
    PRIMARY KEY (source_event_id, related_event_id)
);

-- First create the typed event partner from all legacy shot shared fields. 0005 then makes shots
-- the strictly 1:1 shot-specific detail and removes the duplicated shared columns.
ALTER TABLE shots ADD COLUMN event_id uuid;

INSERT INTO events (
    event_id, match_id, period, minute, second, team_id, player_id, location_x, location_y,
    event_type_name
)
SELECT shot_id::uuid, match_id, period, minute, second, team_id, player_id, location_x, location_y,
       'Shot'
FROM shots;

UPDATE shots SET event_id = shot_id::uuid;

ALTER TABLE shots
    ADD COLUMN outcome_id integer,
    ADD COLUMN outcome_name text,
    ADD COLUMN body_part_id integer,
    ADD COLUMN body_part_name text,
    ADD COLUMN technique_id integer,
    ADD COLUMN technique_name text,
    ADD COLUMN shot_type_id integer,
    ADD COLUMN shot_type_name text,
    ADD COLUMN end_location_x double precision,
    ADD COLUMN end_location_y double precision,
    ADD COLUMN end_location_z double precision,
    ADD COLUMN key_pass_event_id uuid,
    ADD COLUMN aerial_won boolean,
    ADD COLUMN follows_dribble boolean,
    ADD COLUMN first_time boolean,
    ADD COLUMN open_goal boolean,
    ADD COLUMN one_on_one boolean,
    ADD COLUMN deflected boolean,
    ADD COLUMN redirect boolean,
    ADD COLUMN saved_off_target boolean,
    ADD COLUMN saved_to_post boolean;

UPDATE shots
SET outcome_name = outcome,
    body_part_name = body_part,
    technique_name = technique,
    shot_type_name = shot_type;

CREATE TABLE shot_freeze_frame_players (
    freeze_frame_player_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id uuid NOT NULL,
    source_order integer NOT NULL,
    player_id integer,
    teammate boolean NOT NULL,
    position_id integer,
    position_name text,
    location_x double precision,
    location_y double precision,
    UNIQUE (event_id, source_order)
);
