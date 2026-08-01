"""Parser tests against a small committed fixture.

No network, no database. The fixture is two matches with hand-placed edge cases, so each test below
names a source condition and asserts what the parser does with it.

The rule under test throughout: **missing optional data becomes NULL, malformed structure raises.**
A shot with no recorded technique is a real thing. A shot with no team, or a location that is not a
pair of numbers, means the file is not what we think it is - and coercing that into a plausible row
would hide a source or parser misunderstanding rather than surface it.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from touchline.ingest.parse import (
    ParseError,
    parse_competitions,
    parse_events,
    parse_lineups,
    parse_matches,
    parse_shots,
)

FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "statsbomb"


def _load(relative: str) -> Any:
    return json.loads((FIXTURES / relative).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------------
# competitions
# --------------------------------------------------------------------------------------------


def test_competitions_are_keyed_by_competition_and_season() -> None:
    """StatsBomb keys a competition-season as a pair; neither id identifies a row alone."""
    competitions = parse_competitions(_load("competitions.json"))

    keys = {(c.competition_id, c.season_id) for c in competitions}
    assert keys == {(43, 106), (55, 282)}


def test_competition_missing_required_field_raises() -> None:
    with pytest.raises(ParseError, match="season_id"):
        parse_competitions([{"competition_id": 43, "competition_name": "x", "season_name": "y"}])


# --------------------------------------------------------------------------------------------
# matches
# --------------------------------------------------------------------------------------------


def test_matches_parse_with_dates_and_scores() -> None:
    matches, _ = parse_matches(_load("matches/43/106.json"))

    first = next(m for m in matches if m.match_id == 900001)
    assert first.match_date == date(2022, 11, 20)
    assert (first.home_team_id, first.away_team_id) == (7001, 7002)
    assert (first.home_score, first.away_score) == (2, 1)
    assert first.competition_stage == "Group Stage"


def test_absent_competition_stage_becomes_null() -> None:
    """The second fixture match omits competition_stage entirely - optional, so NULL."""
    matches, _ = parse_matches(_load("matches/43/106.json"))

    second = next(m for m in matches if m.match_id == 900002)
    assert second.competition_stage is None


def test_teams_are_deduplicated_across_matches() -> None:
    """Fixture Rovers appears in both matches and must yield one team row, not two."""
    _, teams = parse_matches(_load("matches/43/106.json"))

    ids = [t.team_id for t in teams]
    assert ids == sorted(ids), "teams should be returned in a deterministic order"
    assert len(ids) == len(set(ids)) == 3


def test_unparseable_match_date_raises() -> None:
    payload = _load("matches/43/106.json")
    payload[0]["match_date"] = "20th of November"

    with pytest.raises(ParseError, match="match_date"):
        parse_matches(payload)


# --------------------------------------------------------------------------------------------
# shots
# --------------------------------------------------------------------------------------------


def test_only_shot_events_are_kept() -> None:
    """The fixture holds a Starting XI, a Pass and a Half End alongside four shots."""
    shots, _ = parse_shots(900001, _load("events/900001.json"))

    assert len(shots) == 4


def test_a_match_with_no_shots_yields_nothing_rather_than_failing() -> None:
    shots, players = parse_shots(900002, _load("events/900002.json"))

    assert shots == []
    assert players == []


def test_shot_ids_are_the_statsbomb_event_uuids() -> None:
    """Source identity is preserved verbatim so any row traces back to its source file."""
    shots, _ = parse_shots(900001, _load("events/900001.json"))

    assert all(s.shot_id.startswith("aaaaaaaa-") for s in shots)
    assert len({s.shot_id for s in shots}) == len(shots)


def test_fully_populated_shot_keeps_every_field() -> None:
    shots, _ = parse_shots(900001, _load("events/900001.json"))
    goal = next(s for s in shots if s.shot_id.endswith("003"))

    assert (goal.location_x, goal.location_y) == (112.0, 40.0)
    assert goal.outcome == "Goal"
    assert goal.body_part == "Right Foot"
    assert goal.technique == "Normal"
    assert goal.shot_type == "Open Play"
    assert (goal.period, goal.minute, goal.second) == (1, 23, 5)
    assert goal.player_id == 8002


def test_missing_optional_technique_becomes_null() -> None:
    """An unrecorded technique is a real source condition, not an error."""
    shots, _ = parse_shots(900001, _load("events/900001.json"))
    shot = next(s for s in shots if s.shot_id.endswith("004"))

    assert shot.technique is None
    assert shot.outcome == "Off T"


def test_missing_location_is_null_and_the_shot_is_still_counted() -> None:
    """Dropping such a shot would quietly change the shot count away from the source."""
    shots, _ = parse_shots(900001, _load("events/900001.json"))
    shot = next(s for s in shots if s.shot_id.endswith("005"))

    assert (shot.location_x, shot.location_y) == (None, None)
    assert shot in shots


def test_missing_player_is_null_and_the_shot_is_still_counted() -> None:
    shots, players = parse_shots(900001, _load("events/900001.json"))
    penalty = next(s for s in shots if s.shot_id.endswith("006"))

    assert penalty.player_id is None
    assert penalty.shot_type == "Penalty"
    assert 8002 in {p.player_id for p in players}


def test_provider_xg_is_not_ingested() -> None:
    """The fixture goal carries `statsbomb_xg`, and it must not survive into the record.

    Provider xG is the strongest leakage vector for the M2 shot-quality model. The cheapest way to
    guarantee it never reaches a feature set is for it never to enter the database.
    """
    shots, _ = parse_shots(900001, _load("events/900001.json"))
    goal = next(s for s in shots if s.shot_id.endswith("003"))

    assert not hasattr(goal, "statsbomb_xg")
    assert "0.41" not in repr(goal)


def test_generic_events_keep_directed_relations_and_exclude_provider_xg_recursively() -> None:
    """Residual JSON is useful source fidelity, but never a hiding place for provider xG."""
    payload = [
        {
            "id": "event-a",
            "index": 4,
            "period": 1,
            "minute": 12,
            "second": 3,
            "type": {"id": 30, "name": "Pass"},
            "team": {"id": 7001, "name": "Fixture United"},
            "related_events": ["event-b", "event-c"],
            "pass": {"height": {"id": 1, "name": "Ground Pass"}, "statsbomb_xg": 0.9},
        }
    ]

    events, relations, shots, freeze_frames, possessions, players = parse_events(900001, payload)

    assert len(events) == 1
    assert [(r.event_id, r.related_event_id, r.source_order) for r in relations] == [
        ("event-a", "event-b", 1),
        ("event-a", "event-c", 2),
    ]
    assert events[0].type_data == {"pass": {"height": {"id": 1, "name": "Ground Pass"}}}
    assert shots == []
    assert freeze_frames == []
    assert possessions == []
    assert players == []


def test_lineups_keep_membership_labels_and_source_ordered_positions_and_cards() -> None:
    payload = [
        {
            "team_id": 7001,
            "team_name": "Fixture United",
            "lineup": [
                {
                    "player_id": 8001,
                    "player_name": "Ada Passer",
                    "player_nickname": "Ada",
                    "country": {"id": 1, "name": "Exampleland"},
                    "positions": [
                        {
                            "position_id": 13,
                            "position": "Center Midfield",
                            "from": "00:00",
                            "to": "90:00",
                            "from_period": 1,
                            "to_period": 2,
                        }
                    ],
                    "cards": [
                        {
                            "time": "12:00",
                            "card_type": "Yellow Card",
                            "reason": "Foul Committed",
                            "period": 1,
                        }
                    ],
                }
            ],
        }
    ]

    lineups, memberships, positions, cards, players = parse_lineups(900001, payload)

    assert lineups[0].team_id == 7001
    assert memberships[0].player_nickname == "Ada"
    assert memberships[0].country_name == "Exampleland"
    assert positions[0].source_order == 1
    assert cards[0].source_order == 1
    assert players == [players[0]] and players[0].player_name == "Ada Passer"


def test_lineup_clock_parses_minutes_not_postgres_hours() -> None:
    payload = [
        {
            "team_id": 1,
            "lineup": [{"player_id": 2, "player_name": "P", "positions": [{"from": "101:37"}]}],
        }
    ]
    _, _, positions, _, _ = parse_lineups(1, payload)
    assert positions[0].from_time == timedelta(minutes=101, seconds=37)


def _minimal_lineup_member() -> dict[str, Any]:
    return {"player_id": 2, "player_name": "P"}


def test_lineup_members_container_must_be_a_list() -> None:
    with pytest.raises(ParseError, match="list"):
        parse_lineups(1, [{"team_id": 1, "lineup": {}}])


def test_each_lineup_member_must_be_an_object() -> None:
    with pytest.raises(ParseError, match="object"):
        parse_lineups(1, [{"team_id": 1, "lineup": ["player"]}])


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(
            [{"team_id": True, "lineup": [_minimal_lineup_member()]}], id="boolean-team-id"
        ),
        pytest.param(
            [{"team_id": 1, "lineup": [{"player_id": "2", "player_name": "P"}]}],
            id="string-player-id",
        ),
        pytest.param(
            [{"team_id": 1, "lineup": [{"player_id": 2, "player_name": 3}]}],
            id="numeric-player-name",
        ),
    ],
)
def test_lineup_required_identifiers_and_names_are_not_coerced(
    payload: list[dict[str, Any]],
) -> None:
    with pytest.raises(ParseError, match=r"integer|string"):
        parse_lineups(1, payload)


@pytest.mark.parametrize(
    ("field", "bad_value", "expected_type"),
    [
        pytest.param("player_nickname", 7, "string", id="nickname-number"),
        pytest.param("jersey_number", "7", "integer", id="jersey-string"),
    ],
)
def test_lineup_optional_member_scalars_reject_wrong_runtime_types(
    field: str, bad_value: object, expected_type: str
) -> None:
    member = {**_minimal_lineup_member(), field: bad_value}
    with pytest.raises(ParseError, match=expected_type):
        parse_lineups(1, [{"team_id": 1, "lineup": [member]}])


@pytest.mark.parametrize(
    "country",
    [
        pytest.param("Exampleland", id="not-object"),
        pytest.param({"id": True, "name": "Exampleland"}, id="boolean-id"),
        pytest.param({"id": 1, "name": 2}, id="numeric-name"),
        pytest.param({"id": 1}, id="missing-name"),
    ],
)
def test_lineup_country_requires_a_typed_id_name_pair(country: object) -> None:
    member = {**_minimal_lineup_member(), "country": country}
    with pytest.raises(ParseError, match=r"country|integer|string"):
        parse_lineups(1, [{"team_id": 1, "lineup": [member]}])


@pytest.mark.parametrize("field", ["positions", "cards"])
def test_lineup_child_collections_must_be_lists(field: str) -> None:
    member = {**_minimal_lineup_member(), field: {}}
    with pytest.raises(ParseError, match="list"):
        parse_lineups(1, [{"team_id": 1, "lineup": [member]}])


@pytest.mark.parametrize(
    ("field", "bad_value", "expected_type"),
    [
        pytest.param("position_id", "13", "integer", id="position-id-string"),
        pytest.param("position", 13, "string", id="position-name-number"),
        pytest.param("from_period", "1", "integer", id="position-period-string"),
        pytest.param("start_reason", 1, "string", id="position-reason-number"),
    ],
)
def test_lineup_position_scalars_reject_wrong_runtime_types(
    field: str, bad_value: object, expected_type: str
) -> None:
    member = {**_minimal_lineup_member(), "positions": [{field: bad_value}]}
    with pytest.raises(ParseError, match=expected_type):
        parse_lineups(1, [{"team_id": 1, "lineup": [member]}])


@pytest.mark.parametrize(
    ("card", "expected_type"),
    [
        pytest.param({}, "card_type", id="missing-card-type"),
        pytest.param({"card_type": 1}, "string", id="card-type-number"),
        pytest.param({"card_type": "Yellow Card", "reason": 1}, "string", id="reason-number"),
        pytest.param({"card_type": "Yellow Card", "period": "1"}, "integer", id="period-string"),
    ],
)
def test_lineup_card_scalars_reject_wrong_runtime_types(
    card: dict[str, Any], expected_type: str
) -> None:
    member = {**_minimal_lineup_member(), "cards": [card]}
    with pytest.raises(ParseError, match=expected_type):
        parse_lineups(1, [{"team_id": 1, "lineup": [member]}])


def test_conflicting_possession_teams_raise() -> None:
    base = {
        "period": 1,
        "minute": 1,
        "second": 1,
        "type": {"id": 30, "name": "Pass"},
        "possession": 4,
    }
    payload = [
        {**base, "id": "a", "index": 1, "possession_team": {"id": 1, "name": "A"}},
        {**base, "id": "b", "index": 2, "possession_team": {"id": 2, "name": "B"}},
    ]
    with pytest.raises(ParseError, match="conflicting possession_team"):
        parse_events(1, payload)


# --------------------------------------------------------------------------------------------
# malformed structure
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "bad_value", "expected_type"),
    [
        pytest.param("index", "1", "integer", id="index-string"),
        pytest.param("period", "1", "integer", id="period-string"),
        pytest.param("minute", 1.5, "integer", id="minute-float"),
        pytest.param("second", True, "integer", id="second-boolean"),
        pytest.param("possession", "7", "integer", id="possession-string"),
        pytest.param("duration", "1.25", "numeric", id="duration-string"),
        pytest.param("counterpress", "yes", "boolean", id="boolean-string"),
        pytest.param("timestamp", 123, "string", id="timestamp-number"),
    ],
)
def test_event_optional_scalars_reject_wrong_runtime_types(
    field: str, bad_value: object, expected_type: str
) -> None:
    event: dict[str, Any] = {
        "id": "event-a",
        "type": {"id": 30, "name": "Pass"},
        field: bad_value,
    }

    with pytest.raises(ParseError, match=expected_type):
        parse_events(1, [event])


def test_event_team_and_player_ids_are_not_coerced_from_strings() -> None:
    base = {"id": "event-a", "type": {"id": 30, "name": "Pass"}}
    with pytest.raises(ParseError, match="team"):
        parse_events(1, [{**base, "team": {"id": "1", "name": "A"}}])
    with pytest.raises(ParseError, match=r"player.*id"):
        parse_events(1, [{**base, "player": {"id": "2", "name": "P"}}])


def test_shot_and_freeze_frame_booleans_are_strict() -> None:
    base = {
        "id": "event-a",
        "type": {"id": 16, "name": "Shot"},
        "team": {"id": 1, "name": "A"},
    }
    with pytest.raises(ParseError, match=r"shot\.first_time"):
        parse_events(1, [{**base, "shot": {"first_time": 1}}])
    with pytest.raises(ParseError, match=r"shot\.end_location"):
        parse_events(1, [{**base, "shot": {"end_location": [True, 40.0]}}])
    with pytest.raises(ParseError, match=r"shot\.freeze_frame actor\.teammate"):
        parse_events(
            1,
            [{**base, "shot": {"freeze_frame": [{"teammate": "false"}]}}],
        )


def test_shot_without_a_team_raises() -> None:
    """Team is structural, not optional - a shot belongs to someone."""
    payload = [
        {
            "id": "x",
            "type": {"id": 16, "name": "Shot"},
            "shot": {"outcome": {"id": 97, "name": "Goal"}},
        }
    ]

    with pytest.raises(ParseError, match="team"):
        parse_shots(900001, payload)


def test_shot_without_a_shot_object_raises() -> None:
    payload = [
        {
            "id": "x",
            "type": {"id": 16, "name": "Shot"},
            "team": {"id": 7001, "name": "Fixture United"},
        }
    ]

    with pytest.raises(ParseError, match="shot"):
        parse_shots(900001, payload)


@pytest.mark.parametrize(
    "location",
    [
        pytest.param([112.0], id="one-element"),
        pytest.param([112.0, 40.0, 0.9], id="three-elements"),
        pytest.param("112,40", id="string"),
        pytest.param([112.0, "forty"], id="non-numeric-y"),
        pytest.param([True, 40.0], id="boolean-x"),
    ],
)
def test_malformed_location_raises(location: Any) -> None:
    """A present-but-wrong location is a different thing from an absent one, and must not be
    silently turned into NULL - that would hide a parser or source misunderstanding.

    The three-element case matters specifically: StatsBomb uses `[x, y, z]` elsewhere, for a
    shot's `end_location`. Accepting it here by taking the first two elements would turn a
    misread field into a plausible coordinate.
    """
    payload = [
        {
            "id": "x",
            "type": {"id": 16, "name": "Shot"},
            "team": {"id": 7001, "name": "Fixture United"},
            "location": location,
            "shot": {"outcome": {"id": 97, "name": "Goal"}},
        }
    ]

    with pytest.raises(ParseError, match="location"):
        parse_shots(900001, payload)


def test_categorical_field_of_the_wrong_shape_raises() -> None:
    """StatsBomb categoricals are {"id": .., "name": ..}; a bare string means the format moved."""
    payload = [
        {
            "id": "x",
            "type": {"id": 16, "name": "Shot"},
            "team": {"id": 7001, "name": "Fixture United"},
            "shot": {"outcome": "Goal"},
        }
    ]

    with pytest.raises(ParseError, match="outcome"):
        parse_shots(900001, payload)
