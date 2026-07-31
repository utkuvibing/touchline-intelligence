"""Typed rows produced by parsing, before anything touches the database.

Keeping these separate from both the source JSON and the database lets the parser be tested with
no services running, and makes the shape of what is actually stored explicit in one place.

WP0.3 is a deliberately narrow slice: five tables, no full event model, no lineups, no possessions.
See `schema.sql` for why this schema is temporary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class Competition:
    """One competition-season. StatsBomb keys these as a pair, not individually."""

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
class Shot:
    """A single shot event.

    `shot_id` is StatsBomb's own event UUID, preserved verbatim so any row can be traced back to
    the source file.

    Provider xG is deliberately **not** ingested. It is the strongest possible leakage vector for
    the shot-quality model in M2, and the cheapest way to guarantee it never reaches a feature set
    is for it not to be in the database. If a labelled external comparison is wanted later, it is
    re-ingested then, explicitly and separately.
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
