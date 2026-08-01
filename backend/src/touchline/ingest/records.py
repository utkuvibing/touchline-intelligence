"""Typed source rows.  Source JSON never crosses this boundary unexamined."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


@dataclass(frozen=True, slots=True)
class Competition:
    competition_id: int
    season_id: int
    competition_name: str
    season_name: str
    country_name: str | None


@dataclass(frozen=True, slots=True)
class Team:
    team_id: int
    team_name: str


@dataclass(frozen=True, slots=True)
class Player:
    player_id: int
    player_name: str


@dataclass(frozen=True, slots=True)
class Match:
    match_id: int
    competition_id: int
    season_id: int
    match_date: date | None
    kick_off: str | None
    home_team_id: int
    away_team_id: int
    home_score: int | None
    away_score: int | None
    competition_stage: str | None


@dataclass(frozen=True, slots=True)
class Lineup:
    match_id: int
    team_id: int


@dataclass(frozen=True, slots=True)
class LineupMembership:
    match_id: int
    team_id: int
    player_id: int
    player_name: str
    player_nickname: str | None
    country_id: int | None
    country_name: str | None
    jersey_number: int | None = None


@dataclass(frozen=True, slots=True)
class LineupPosition:
    match_id: int
    team_id: int
    player_id: int
    source_order: int
    position_id: int | None
    position_name: str | None
    from_time: timedelta | None
    to_time: timedelta | None
    from_period: int | None
    to_period: int | None
    start_reason: str | None = None
    end_reason: str | None = None


@dataclass(frozen=True, slots=True)
class LineupCard:
    match_id: int
    team_id: int
    player_id: int
    source_order: int
    time: timedelta | None
    card_type: str | None
    reason: str | None
    period: int | None


@dataclass(frozen=True, slots=True)
class Possession:
    match_id: int
    possession_id: int
    team_id: int | None


@dataclass(frozen=True, slots=True)
class Event:
    event_id: str
    match_id: int
    source_index: int | None
    period: int | None
    minute: int | None
    second: int | None
    possession_id: int | None
    team_id: int | None
    player_id: int | None
    type_id: int
    type_name: str
    location_x: float | None
    location_y: float | None
    type_data: dict[str, Any] | None
    timestamp: str | None = None
    play_pattern_id: int | None = None
    play_pattern_name: str | None = None
    position_id: int | None = None
    position_name: str | None = None
    duration: float | None = None
    counterpress: bool | None = None
    under_pressure: bool | None = None
    off_camera: bool | None = None
    out: bool | None = None


@dataclass(frozen=True, slots=True)
class EventRelation:
    match_id: int
    event_id: str
    related_event_id: str
    source_order: int


@dataclass(frozen=True, slots=True)
class Shot:
    """Parsed Shot detail plus its shared source event fields.

    The shared fields keep the established ``parse_shots`` interface and support pre-load coverage
    counts. ``Event`` owns their normalized persistence; the loader writes only the shot-specific
    fields below to ``shots``.
    """

    shot_id: str
    match_id: int
    team_id: int
    player_id: int | None
    period: int | None
    minute: int | None
    second: int | None
    location_x: float | None
    location_y: float | None
    outcome: str | None
    body_part: str | None
    technique: str | None
    shot_type: str | None
    outcome_id: int | None = None
    body_part_id: int | None = None
    technique_id: int | None = None
    shot_type_id: int | None = None
    end_location_x: float | None = None
    end_location_y: float | None = None
    end_location_z: float | None = None
    key_pass_event_id: str | None = None
    aerial_won: bool | None = None
    deflected: bool | None = None
    first_time: bool | None = None
    follows_dribble: bool | None = None
    open_goal: bool | None = None
    one_on_one: bool | None = None
    redirect: bool | None = None
    saved_off_target: bool | None = None
    saved_to_post: bool | None = None


@dataclass(frozen=True, slots=True)
class ShotFreezeFramePlayer:
    shot_id: str
    source_order: int
    player_id: int | None
    teammate: bool | None
    position_id: int | None
    position_name: str | None
    location_x: float | None
    location_y: float | None
