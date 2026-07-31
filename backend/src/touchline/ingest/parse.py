"""Pure JSON-to-record parsing.

No network, no database, no filesystem — everything here is a function from parsed JSON to typed
records, which is what makes it testable against a small committed fixture.

Design rule for this module: **missing optional data is preserved as NULL, malformed structure
raises.** A shot with no recorded technique is a real thing and becomes NULL. A shot with no team,
or a location that is not a two-element list, means the file is not what we think it is, and
silently coercing it would hide a source or parser misunderstanding behind plausible-looking rows.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from touchline.ingest.records import Competition, Match, Player, Shot, Team

SHOT_EVENT_TYPE = "Shot"


class ParseError(ValueError):
    """The source structure is not what the parser expects.

    Distinct from missing optional values, which are not errors.
    """


def _require(obj: Any, key: str, context: str) -> Any:
    if not isinstance(obj, dict) or key not in obj:
        raise ParseError(f"{context}: missing required field {key!r}")
    value = obj[key]
    if value is None:
        raise ParseError(f"{context}: required field {key!r} is null")
    return value


def _nested_name(obj: dict[str, Any], key: str) -> str | None:
    """Read `obj[key]["name"]` where the whole key may be absent.

    StatsBomb models categorical values as `{"id": .., "name": ..}` objects that are simply omitted
    when they do not apply, so absence is normal and means NULL.
    """
    nested = obj.get(key)
    if nested is None:
        return None
    if not isinstance(nested, dict) or "name" not in nested:
        raise ParseError(f"expected {key!r} to be an object with a 'name', got {nested!r}")
    name = nested["name"]
    if not isinstance(name, str):
        raise ParseError(f"expected {key!r}.name to be a string, got {name!r}")
    return name


def _location(event: dict[str, Any]) -> tuple[float | None, float | None]:
    """Split a StatsBomb `[x, y]` location.

    Absent location is tolerated and becomes (NULL, NULL) so the row is still recorded and can be
    counted in a coverage report. A location that is present but is not **exactly** two numbers is
    malformed and raises.

    Exactly two, not "at least two": StatsBomb does use three-element coordinates elsewhere - a
    shot's `end_location` carries a z for the ball's height at the goal line. If such a value ever
    appeared in the `location` field, silently taking the first two elements would produce a
    plausible-looking row from a field we had misunderstood. Length is the cheapest signal that the
    source is not what this parser thinks it is, so it is checked rather than tolerated.
    """
    raw = event.get("location")
    if raw is None:
        return None, None
    if not isinstance(raw, list) or len(raw) != 2:
        raise ParseError(f"expected location to be exactly [x, y], got {raw!r}")
    x, y = raw
    if not isinstance(x, int | float) or not isinstance(y, int | float):
        raise ParseError(f"expected numeric location, got {raw!r}")
    return float(x), float(y)


def parse_competitions(payload: list[dict[str, Any]]) -> list[Competition]:
    """Parse `competitions.json` into competition-season rows."""
    out: list[Competition] = []
    for row in payload:
        ctx = "competitions.json entry"
        out.append(
            Competition(
                competition_id=int(_require(row, "competition_id", ctx)),
                season_id=int(_require(row, "season_id", ctx)),
                competition_name=str(_require(row, "competition_name", ctx)),
                season_name=str(_require(row, "season_name", ctx)),
                country_name=row.get("country_name"),
            )
        )
    return out


def _parse_match_date(raw: Any) -> date | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ParseError(f"expected match_date to be a string, got {raw!r}")
    try:
        return date.fromisoformat(raw[:10])
    except ValueError as exc:
        raise ParseError(f"unparseable match_date {raw!r}") from exc


def parse_matches(payload: list[dict[str, Any]]) -> tuple[list[Match], list[Team]]:
    """Parse a `matches/<competition>/<season>.json` file.

    Teams are returned alongside because the match file is where team identities appear; collecting
    them here avoids reading every event file just to learn team names.
    """
    matches: list[Match] = []
    teams: dict[int, Team] = {}

    for row in payload:
        ctx = "match entry"
        home = _require(row, "home_team", ctx)
        away = _require(row, "away_team", ctx)
        competition = _require(row, "competition", ctx)
        season = _require(row, "season", ctx)

        home_id = int(_require(home, "home_team_id", ctx))
        away_id = int(_require(away, "away_team_id", ctx))
        teams[home_id] = Team(home_id, str(_require(home, "home_team_name", ctx)))
        teams[away_id] = Team(away_id, str(_require(away, "away_team_name", ctx)))

        matches.append(
            Match(
                match_id=int(_require(row, "match_id", ctx)),
                competition_id=int(_require(competition, "competition_id", ctx)),
                season_id=int(_require(season, "season_id", ctx)),
                match_date=_parse_match_date(row.get("match_date")),
                kick_off=row.get("kick_off"),
                home_team_id=home_id,
                away_team_id=away_id,
                home_score=row.get("home_score"),
                away_score=row.get("away_score"),
                competition_stage=_nested_name(row, "competition_stage"),
            )
        )

    return matches, sorted(teams.values(), key=lambda t: t.team_id)


def parse_shots(match_id: int, payload: list[dict[str, Any]]) -> tuple[list[Shot], list[Player]]:
    """Extract shots and the players who took them from one match's event file.

    Every non-shot event is ignored. WP0.3 stores no other event type on purpose — the full event
    model is M1 work.
    """
    shots: list[Shot] = []
    players: dict[int, Player] = {}

    for event in payload:
        if _nested_name(event, "type") != SHOT_EVENT_TYPE:
            continue

        ctx = f"shot in match {match_id}"
        shot_detail = _require(event, "shot", ctx)
        team = _require(event, "team", ctx)
        x, y = _location(event)

        player = event.get("player")
        player_id: int | None = None
        if player is not None:
            player_id = int(_require(player, "id", ctx))
            players[player_id] = Player(player_id, str(_require(player, "name", ctx)))

        shots.append(
            Shot(
                shot_id=str(_require(event, "id", ctx)),
                match_id=match_id,
                team_id=int(_require(team, "id", ctx)),
                player_id=player_id,
                period=event.get("period"),
                minute=event.get("minute"),
                second=event.get("second"),
                location_x=x,
                location_y=y,
                outcome=_nested_name(shot_detail, "outcome"),
                body_part=_nested_name(shot_detail, "body_part"),
                technique=_nested_name(shot_detail, "technique"),
                shot_type=_nested_name(shot_detail, "type"),
            )
        )

    return shots, sorted(players.values(), key=lambda p: p.player_id)
