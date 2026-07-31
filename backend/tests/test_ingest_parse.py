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
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from touchline.ingest.parse import (
    ParseError,
    parse_competitions,
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


# --------------------------------------------------------------------------------------------
# malformed structure
# --------------------------------------------------------------------------------------------


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
        pytest.param("112,40", id="string"),
        pytest.param([112.0, "forty"], id="non-numeric-y"),
    ],
)
def test_malformed_location_raises(location: Any) -> None:
    """A present-but-wrong location is a different thing from an absent one, and must not be
    silently turned into NULL - that would hide a parser or source misunderstanding."""
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
