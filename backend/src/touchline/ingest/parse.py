"""Pure StatsBomb JSON to explicit typed records."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from touchline.ingest.records import (
    Competition,
    Event,
    EventRelation,
    Lineup,
    LineupCard,
    LineupMembership,
    LineupPosition,
    Match,
    Player,
    Possession,
    Shot,
    ShotFreezeFramePlayer,
    Team,
)

SHOT_EVENT_TYPE = "Shot"


class ParseError(ValueError):
    pass


def _require(obj: Any, key: str, context: str) -> Any:
    if not isinstance(obj, dict) or obj.get(key) is None:
        raise ParseError(f"{context}: missing required field {key!r}")
    return obj[key]


def _required_int(obj: Any, key: str, context: str) -> int:
    value = _require(obj, key, context)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ParseError(f"expected {context}.{key} to be an integer, got {value!r}")
    return value


def _required_str(obj: Any, key: str, context: str) -> str:
    value = _require(obj, key, context)
    if not isinstance(value, str):
        raise ParseError(f"expected {context}.{key} to be a string, got {value!r}")
    return value


def _optional_int(obj: dict[str, Any], key: str, context: str) -> int | None:
    value = obj.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ParseError(f"expected {context}.{key} to be an integer, got {value!r}")
    return value


def _optional_number(obj: dict[str, Any], key: str, context: str) -> float | None:
    value = obj.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ParseError(f"expected {context}.{key} to be numeric, got {value!r}")
    return float(value)


def _optional_bool(obj: dict[str, Any], key: str, context: str) -> bool | None:
    value = obj.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ParseError(f"expected {context}.{key} to be boolean, got {value!r}")
    return value


def _optional_str(obj: dict[str, Any], key: str, context: str) -> str | None:
    value = obj.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ParseError(f"expected {context}.{key} to be a string, got {value!r}")
    return value


def _nested_name(obj: dict[str, Any], key: str) -> str | None:
    v = obj.get(key)
    if v is None:
        return None
    if not isinstance(v, dict) or not isinstance(v.get("name"), str):
        raise ParseError(f"expected {key!r} to be an object with a 'name', got {v!r}")
    return str(v["name"])


def _nested_id(obj: dict[str, Any], key: str) -> int | None:
    value = obj.get(key)
    if value is None:
        return None
    if (
        not isinstance(value, dict)
        or isinstance(value.get("id"), bool)
        or not isinstance(value.get("id"), int)
    ):
        raise ParseError(f"expected {key!r} to be an object with an integer 'id', got {value!r}")
    return int(value["id"])


def _end_location(shot: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    value = shot.get("end_location")
    if value is None:
        return None, None, None
    if (
        not isinstance(value, list)
        or len(value) not in (2, 3)
        or not all(
            not isinstance(coordinate, bool) and isinstance(coordinate, int | float)
            for coordinate in value
        )
    ):
        raise ParseError(f"expected shot.end_location to be [x, y] or [x, y, z], got {value!r}")
    return float(value[0]), float(value[1]), None if len(value) == 2 else float(value[2])


def _clock(value: Any, context: str) -> timedelta | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ParseError(f"expected {context} to be MM:SS, got {value!r}")
    parts = value.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ParseError(f"expected {context} to be MM:SS, got {value!r}")
    minutes, seconds = (int(part) for part in parts)
    if seconds > 59:
        raise ParseError(f"expected {context} seconds to be 0-59, got {value!r}")
    return timedelta(minutes=minutes, seconds=seconds)


def _location(event: dict[str, Any]) -> tuple[float | None, float | None]:
    v = event.get("location")
    if v is None:
        return None, None
    if (
        not isinstance(v, list)
        or len(v) != 2
        or not all(not isinstance(x, bool) and isinstance(x, int | float) for x in v)
    ):
        raise ParseError(f"expected location to be exactly [x, y], got {v!r}")
    return float(v[0]), float(v[1])


def _strip_xg(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_xg(v) for k, v in value.items() if k != "statsbomb_xg"}
    if isinstance(value, list):
        return [_strip_xg(v) for v in value]
    return value


def _category(value: Any, context: str) -> tuple[int, str]:
    if (
        not isinstance(value, dict)
        or isinstance(value.get("id"), bool)
        or not isinstance(value.get("id"), int)
        or not isinstance(value.get("name"), str)
    ):
        raise ParseError(f"expected {context} to be an id/name categorical object, got {value!r}")
    return value["id"], value["name"]


def _residual(event: dict[str, Any], event_type_name: str) -> dict[str, Any] | None:
    """Preserve only non-shared source keys, never provider xG or Shot payloads."""
    shared = {
        "id",
        "index",
        "period",
        "timestamp",
        "minute",
        "second",
        "type",
        "possession",
        "possession_team",
        "play_pattern",
        "team",
        "player",
        "position",
        "duration",
        "location",
        "related_events",
        "tactics",
        "counterpress",
        "under_pressure",
        "off_camera",
        "out",
    }
    if event_type_name == SHOT_EVENT_TYPE:
        return None
    result = {
        key: value for key, value in event.items() if key not in shared and not key.startswith("_")
    }
    return _strip_xg(result) or None


def _type_data(event: dict[str, Any], event_type_name: str) -> dict[str, Any] | None:
    residual = _residual(event, event_type_name)
    if event_type_name == SHOT_EVENT_TYPE:
        return None
    tactics = event.get("tactics")
    if tactics is None:
        return residual
    if not isinstance(tactics, dict):
        raise ParseError("expected tactics to be an object")
    return {**(residual or {}), "tactics": _strip_xg(tactics)}


def _player(value: Any, ctx: str) -> Player | None:
    if value is None:
        return None
    player_context = f"{ctx}.player"
    return Player(
        _required_int(value, "id", player_context),
        _required_str(value, "name", player_context),
    )


def parse_competitions(payload: list[dict[str, Any]]) -> list[Competition]:
    return [
        Competition(
            int(_require(r, "competition_id", "competitions.json entry")),
            int(_require(r, "season_id", "competitions.json entry")),
            str(_require(r, "competition_name", "competitions.json entry")),
            str(_require(r, "season_name", "competitions.json entry")),
            r.get("country_name"),
        )
        for r in payload
    ]


def _parse_match_date(v: Any) -> date | None:
    if v is None:
        return None
    if not isinstance(v, str):
        raise ParseError(f"expected match_date to be a string, got {v!r}")
    try:
        return date.fromisoformat(v[:10])
    except ValueError as e:
        raise ParseError(f"unparseable match_date {v!r}") from e


def parse_matches(payload: list[dict[str, Any]]) -> tuple[list[Match], list[Team]]:
    ms = []
    ts = {}
    for r in payload:
        h = _require(r, "home_team", "match entry")
        a = _require(r, "away_team", "match entry")
        c = _require(r, "competition", "match entry")
        s = _require(r, "season", "match entry")
        hi = int(_require(h, "home_team_id", "match entry"))
        ai = int(_require(a, "away_team_id", "match entry"))
        ts[hi] = Team(hi, str(_require(h, "home_team_name", "match entry")))
        ts[ai] = Team(ai, str(_require(a, "away_team_name", "match entry")))
        ms.append(
            Match(
                int(_require(r, "match_id", "match entry")),
                int(_require(c, "competition_id", "match entry")),
                int(_require(s, "season_id", "match entry")),
                _parse_match_date(r.get("match_date")),
                r.get("kick_off"),
                hi,
                ai,
                r.get("home_score"),
                r.get("away_score"),
                _nested_name(r, "competition_stage"),
            )
        )
    return ms, sorted(ts.values(), key=lambda x: x.team_id)


def parse_lineups(
    match_id: int, payload: list[dict[str, Any]]
) -> tuple[
    list[Lineup], list[LineupMembership], list[LineupPosition], list[LineupCard], list[Player]
]:
    ls = []
    ms = []
    ps = []
    cs = []
    players = {}
    for team in payload:
        team_context = f"lineup in match {match_id}"
        tid = _required_int(team, "team_id", team_context)
        if isinstance(team, dict) and team.get("team_name") is not None:
            _required_str(team, "team_name", team_context)
        ls.append(Lineup(match_id, tid))
        raw_lineup = _require(team, "lineup", team_context)
        if not isinstance(raw_lineup, list):
            raise ParseError(f"expected {team_context}.lineup to be a list, got {raw_lineup!r}")
        for entry in raw_lineup:
            if not isinstance(entry, dict):
                raise ParseError(f"expected {team_context}.lineup member to be an object")
            member_context = "lineup member"
            pid = _required_int(entry, "player_id", member_context)
            name = _required_str(entry, "player_name", member_context)
            country = entry.get("country")
            if country is not None and not isinstance(country, dict):
                raise ParseError("expected country to be an object")
            country_id = None
            country_name = None
            if country is not None:
                country_id = _required_int(country, "id", "lineup member.country")
                country_name = _required_str(country, "name", "lineup member.country")
            ms.append(
                LineupMembership(
                    match_id,
                    tid,
                    pid,
                    name,
                    _optional_str(entry, "player_nickname", member_context),
                    country_id,
                    country_name,
                    _optional_int(entry, "jersey_number", member_context),
                )
            )
            players[pid] = Player(pid, name)
            positions = entry.get("positions", [])
            if not isinstance(positions, list):
                raise ParseError("expected lineup member.positions to be a list")
            for i, p in enumerate(positions, start=1):
                if not isinstance(p, dict):
                    raise ParseError("expected position to be an object")
                position_id = _optional_int(p, "position_id", "lineup position")
                position_name = _optional_str(p, "position", "lineup position")
                if (position_id is None) != (position_name is None):
                    raise ParseError("lineup position id and name must both be present or absent")
                ps.append(
                    LineupPosition(
                        match_id,
                        tid,
                        pid,
                        i,
                        position_id,
                        position_name,
                        _clock(p.get("from"), "lineup position from"),
                        _clock(p.get("to"), "lineup position to"),
                        _optional_int(p, "from_period", "lineup position"),
                        _optional_int(p, "to_period", "lineup position"),
                        _optional_str(p, "start_reason", "lineup position"),
                        _optional_str(p, "end_reason", "lineup position"),
                    )
                )
            cards = entry.get("cards", [])
            if not isinstance(cards, list):
                raise ParseError("expected lineup member.cards to be a list")
            for i, c in enumerate(cards, start=1):
                if not isinstance(c, dict):
                    raise ParseError("expected card to be an object")
                cs.append(
                    LineupCard(
                        match_id,
                        tid,
                        pid,
                        i,
                        _clock(c.get("time"), "lineup card time"),
                        _required_str(c, "card_type", "lineup card"),
                        _optional_str(c, "reason", "lineup card"),
                        _optional_int(c, "period", "lineup card"),
                    )
                )
    return ls, ms, ps, cs, sorted(players.values(), key=lambda p: p.player_id)


def parse_events(
    match_id: int, payload: list[dict[str, Any]]
) -> tuple[
    list[Event],
    list[EventRelation],
    list[Shot],
    list[ShotFreezeFramePlayer],
    list[Possession],
    list[Player],
]:
    events = []
    rels: list[EventRelation] = []
    shots = []
    frames = []
    poss: dict[int, Possession] = {}
    players = {}
    for event in payload:
        ctx = f"event in match {match_id}"
        event_id = _require(event, "id", ctx)
        if not isinstance(event_id, str):
            raise ParseError(f"expected event id in {ctx} to be a string, got {event_id!r}")
        eid = event_id
        tid, tname = _category(_require(event, "type", ctx), f"type in {ctx}")
        team = event.get("team")
        player = _player(event.get("player"), ctx)
        x, y = _location(event)
        if player:
            players[player.player_id] = player
        team_id = None if team is None else _category(team, f"team in {ctx}")[0]
        possid = _optional_int(event, "possession", ctx)
        possession_team = event.get("possession_team")
        possession_team_id = (
            None
            if possession_team is None
            else _category(possession_team, f"possession_team in {ctx}")[0]
        )
        if possid is not None:
            possession_id = possid
            prior = poss.get(possession_id)
            if prior is not None and prior.team_id != possession_team_id:
                raise ParseError(
                    "conflicting possession_team for possession "
                    f"{possession_id} in match {match_id}"
                )
            poss[possession_id] = Possession(match_id, possession_id, possession_team_id)
        events.append(
            Event(
                event_id=eid,
                match_id=match_id,
                source_index=_optional_int(event, "index", ctx),
                period=_optional_int(event, "period", ctx),
                minute=_optional_int(event, "minute", ctx),
                second=_optional_int(event, "second", ctx),
                possession_id=possid,
                team_id=team_id,
                player_id=None if player is None else player.player_id,
                type_id=tid,
                type_name=tname,
                location_x=x,
                location_y=y,
                type_data=_type_data(event, tname),
                timestamp=_optional_str(event, "timestamp", ctx),
                play_pattern_id=_nested_id(event, "play_pattern"),
                play_pattern_name=_nested_name(event, "play_pattern"),
                position_id=_nested_id(event, "position"),
                position_name=_nested_name(event, "position"),
                duration=_optional_number(event, "duration", ctx),
                counterpress=_optional_bool(event, "counterpress", ctx),
                under_pressure=_optional_bool(event, "under_pressure", ctx),
                off_camera=_optional_bool(event, "off_camera", ctx),
                out=_optional_bool(event, "out", ctx),
            )
        )
        related = event.get("related_events", [])
        if not isinstance(related, list) or not all(isinstance(v, str) for v in related):
            raise ParseError(f"expected related_events list of ids in {ctx}")
        rels.extend(EventRelation(match_id, eid, v, i) for i, v in enumerate(related, start=1))
        if tname == SHOT_EVENT_TYPE:
            detail = _require(event, "shot", ctx)
            if not isinstance(detail, dict):
                raise ParseError(f"expected shot in {ctx} to be an object, got {detail!r}")
            if team is None:
                raise ParseError(f"{ctx}: missing required field 'team'")
            if team_id is None:  # Narrows the optional generic-event association for Shot.
                raise ParseError(f"{ctx}: missing required field 'team.id'")
            end_x, end_y, end_z = _end_location(detail)
            shots.append(
                Shot(
                    eid,
                    match_id,
                    team_id,
                    None if player is None else player.player_id,
                    _optional_int(event, "period", ctx),
                    _optional_int(event, "minute", ctx),
                    _optional_int(event, "second", ctx),
                    x,
                    y,
                    _nested_name(detail, "outcome"),
                    _nested_name(detail, "body_part"),
                    _nested_name(detail, "technique"),
                    _nested_name(detail, "type"),
                    _nested_id(detail, "outcome"),
                    _nested_id(detail, "body_part"),
                    _nested_id(detail, "technique"),
                    _nested_id(detail, "type"),
                    end_x,
                    end_y,
                    end_z,
                    _optional_str(detail, "key_pass_id", "shot"),
                    _optional_bool(detail, "aerial_won", "shot"),
                    _optional_bool(detail, "deflected", "shot"),
                    _optional_bool(detail, "first_time", "shot"),
                    _optional_bool(detail, "follows_dribble", "shot"),
                    _optional_bool(detail, "open_goal", "shot"),
                    _optional_bool(detail, "one_on_one", "shot"),
                    _optional_bool(detail, "redirect", "shot"),
                    _optional_bool(detail, "saved_off_target", "shot"),
                    _optional_bool(detail, "saved_to_post", "shot"),
                )
            )
            ff = detail.get("freeze_frame", [])
            if not isinstance(ff, list):
                raise ParseError("expected shot.freeze_frame to be a list")
            for i, actor in enumerate(ff, start=1):
                if not isinstance(actor, dict):
                    raise ParseError("expected freeze-frame actor object")
                ax, ay = _location(actor)
                ap = _player(actor.get("player"), ctx)
                if ap:
                    players[ap.player_id] = ap
                frames.append(
                    ShotFreezeFramePlayer(
                        eid,
                        i,
                        None if ap is None else ap.player_id,
                        _optional_bool(actor, "teammate", "shot.freeze_frame actor"),
                        _nested_id(actor, "position"),
                        _nested_name(actor, "position"),
                        ax,
                        ay,
                    )
                )
    return (
        events,
        rels,
        shots,
        frames,
        sorted(poss.values(), key=lambda p: p.possession_id),
        sorted(players.values(), key=lambda p: p.player_id),
    )


def parse_shots(match_id: int, payload: list[dict[str, Any]]) -> tuple[list[Shot], list[Player]]:
    _, _, shots, _, _, players = parse_events(match_id, payload)
    shooting_player_ids = {shot.player_id for shot in shots if shot.player_id is not None}
    return shots, [player for player in players if player.player_id in shooting_player_ids]
