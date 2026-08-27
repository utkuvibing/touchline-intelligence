"""Target-free source observations for M6 WP6.1.

This module is deliberately a *canonical boundary*, rather than an early feature matrix.  It
contains only recorded pre-shot facts and derived pre-shot context.  In particular it contains no
shot outcome, model value, player/team identity feature, post-shot coordinate or provider xG.
Later work packages may turn these observations into fitted features, but may not widen this
boundary silently.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

import psycopg

from touchline.features.geometry import distance_to_goal, visible_goal_angle
from touchline.modeling.v2_folds import development_pool_scopes
from touchline.sealed_scope import SEALED_SCOPES, SEALED_SET_NAMES, SealedScopeError

CONTEXT_SCHEMA_VERSION = "1.0"
WP6_1_DEVELOPMENT_SCOPE_NAMES = MappingProxyType(
    {(43, 3): "WC2018", (55, 43): "Euro2020", (43, 106): "WC2022", (55, 282): "Euro2024"}
)
WP6_1_DEVELOPMENT_SCOPES = frozenset(WP6_1_DEVELOPMENT_SCOPE_NAMES)
_PROVIDER_XG_TEXT = re.compile(
    r"statsbomb[_ -]?xg|provider[_ -]?xg|expected[_ -]?goals|(?:^|[^a-z0-9])xg(?:$|[^a-z0-9])",
    re.IGNORECASE,
)


class ContextBoundaryError(ValueError):
    """A value attempted to cross the target-free canonical context boundary."""


class ContextLoadError(ValueError):
    """A source-shaped row does not have the structure required for a context observation."""


@dataclass(frozen=True, slots=True)
class V2ShotMetadata:
    """Audit identity and scope, kept separate from candidate feature observations."""

    shot_id: str
    match_id: int
    competition_id: int
    season_id: int
    tournament: str
    match_date: dt.date
    event_index: int


@dataclass(frozen=True, slots=True)
class V2FreezeFrameActor:
    """One source-shaped embedded freeze-frame actor; no inferred position is added."""

    source_order: int
    teammate: bool
    position_name: str | None
    location_x: float | None
    location_y: float | None

    def __post_init__(self) -> None:
        if self.source_order < 1:
            raise ContextBoundaryError("freeze-frame source_order must be positive")
        if (self.location_x is None) != (self.location_y is None):
            raise ContextBoundaryError("freeze-frame coordinates must both be present or absent")
        if self.location_x is not None and not 0.0 <= self.location_x <= 120.0:
            raise ContextBoundaryError("freeze-frame location_x is outside [0, 120]")
        if self.location_y is not None and not 0.0 <= self.location_y <= 80.0:
            raise ContextBoundaryError("freeze-frame location_y is outside [0, 80]")


@dataclass(frozen=True, slots=True)
class V2PrecedingAction:
    """The immediately preceding recorded event in the same possession, when present."""

    event_type_name: str
    displacement: float | None
    end_zone: str | None
    is_supported_action: bool


@dataclass(frozen=True, slots=True)
class V2ShotContext:
    """Versioned, target-free pre-shot context.

    Fields intentionally contain no residual mapping.  That makes it impossible for ignored raw
    fields such as ``statsbomb_xg`` to survive accidentally through a generic JSON escape hatch.
    """

    schema_version: str
    location_x: float
    location_y: float
    distance_to_goal: float
    visible_goal_angle: float
    body_part_name: str
    technique_name: str
    shot_type_name: str
    play_pattern_name: str | None
    under_pressure: bool | None
    first_time: bool | None
    period: int | None
    minute: int | None
    second: int | None
    match_clock_seconds: int | None
    team_score_before: int
    opponent_score_before: int
    possession_id: int | None
    possession_duration_seconds: float | None
    possession_action_count_before: int | None
    preceding_action: V2PrecedingAction | None
    key_pass_event_type: str | None
    key_pass_length: float | None
    freeze_frame: tuple[V2FreezeFrameActor, ...]

    def __post_init__(self) -> None:
        if self.schema_version != CONTEXT_SCHEMA_VERSION:
            raise ContextBoundaryError(
                f"V2ShotContext schema_version {self.schema_version!r} is not "
                f"{CONTEXT_SCHEMA_VERSION!r}"
            )
        expected_distance = distance_to_goal(self.location_x, self.location_y)
        expected_angle = visible_goal_angle(self.location_x, self.location_y)
        if not math.isclose(self.distance_to_goal, expected_distance, rel_tol=0.0, abs_tol=1e-12):
            raise ContextBoundaryError("distance_to_goal does not match the recorded location")
        if not math.isclose(self.visible_goal_angle, expected_angle, rel_tol=0.0, abs_tol=1e-12):
            raise ContextBoundaryError("visible_goal_angle does not match the recorded location")
        if not self.body_part_name or not self.technique_name or not self.shot_type_name:
            raise ContextBoundaryError("required shot categories must be non-empty")
        if self.team_score_before < 0 or self.opponent_score_before < 0:
            raise ContextBoundaryError("pre-shot scores must be nonnegative")
        if self.possession_duration_seconds is not None and self.possession_duration_seconds < 0:
            raise ContextBoundaryError("possession duration must be nonnegative")
        if self.possession_id is None and (
            self.possession_duration_seconds is not None
            or self.possession_action_count_before is not None
        ):
            raise ContextBoundaryError("missing possession cannot carry derived possession facts")
        if self.key_pass_length is not None:
            raise ContextBoundaryError("key-pass length is not normalized in context schema 1.0")
        if self.preceding_action is not None and self.preceding_action.end_zone is not None:
            raise ContextBoundaryError(
                "preceding-event end zone is unsupported in context schema 1.0"
            )
        _assert_no_provider_xg(self, "V2ShotContext")


@dataclass(frozen=True, slots=True)
class V2ContextObservation:
    """The only object passed from the context seam to coverage/audit code."""

    metadata: V2ShotMetadata
    context: V2ShotContext


def _assert_no_provider_xg(value: object, boundary: str) -> None:
    """Reject provider xG at the typed boundary, while raw ingestion may quarantine it earlier."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            if contains_provider_xg_name(str(key)):
                raise ContextBoundaryError(
                    f"provider xG crossed the {boundary} boundary via {key!r}"
                )
            _assert_no_provider_xg(child, boundary)
    elif isinstance(value, (tuple, list)):
        for child in value:
            _assert_no_provider_xg(child, boundary)
    elif isinstance(value, str) and contains_provider_xg_name(value):
        raise ContextBoundaryError(f"provider xG crossed the {boundary} boundary via a value")
    elif hasattr(value, "__dataclass_fields__"):
        for key in value.__dataclass_fields__:
            if contains_provider_xg_name(key):
                raise ContextBoundaryError(
                    f"provider xG crossed the {boundary} boundary via {key!r}"
                )
            _assert_no_provider_xg(getattr(value, key), boundary)


def contains_provider_xg_name(value: str) -> bool:
    """Return whether a field or serialized name denotes provider expected-goals data."""
    return _PROVIDER_XG_TEXT.search(value) is not None


def assert_context_boundary(value: object) -> None:
    """Public guard used by loaders and artifact writers before contexts leave this module."""
    _assert_no_provider_xg(value, "V2ShotContext")


def _tournament_names(config: Mapping[str, Any]) -> Mapping[tuple[int, int], str]:
    pool = config.get("development_pool")
    if not isinstance(pool, list):
        raise ContextLoadError("protocol config has no development_pool list")
    names: dict[tuple[int, int], str] = {}
    for entry in pool:
        if not isinstance(entry, Mapping):
            raise ContextLoadError("protocol development_pool entry is not an object")
        try:
            names[(int(entry["competition_id"]), int(entry["season_id"]))] = str(entry["name"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ContextLoadError(f"malformed protocol development_pool entry: {entry!r}") from exc
    return MappingProxyType(names)


def permitted_development_scopes(config: Mapping[str, Any]) -> frozenset[tuple[int, int]]:
    """Return exactly the four protocol development scopes, rejecting a sealed collision."""
    scopes = development_pool_scopes(config)
    collision = scopes & SEALED_SCOPES
    if collision:
        pair = sorted(collision)[0]
        raise SealedScopeError(
            f"protocol development pool includes sealed {pair} ({SEALED_SET_NAMES[pair]})"
        )
    if scopes != WP6_1_DEVELOPMENT_SCOPES:
        raise ContextLoadError(
            "WP6.1 protocol must contain exactly WC 2018, Euro 2020, WC 2022, and Euro 2024"
        )
    return scopes


# This projection deliberately excludes shots.outcome_name and every post-shot column.  Scores are
# computed by the database from strictly earlier scoring events and arrive only as integers.
CONTEXT_LOAD_SQL = """
WITH scoped(competition_id, season_id) AS (VALUES %s),
scoped_matches AS (
    SELECT m.match_id, m.competition_id, m.season_id, m.match_date
    FROM matches AS m JOIN scoped AS scope USING (competition_id, season_id)
), scoped_shots AS (
    SELECT e.event_id::text, e.match_id, sm.competition_id, sm.season_id, sm.match_date,
           e.event_index,
           e.team_id, e.period, e.timestamp, e.minute, e.second, e.possession_id,
           e.location_x, e.location_y,
           e.play_pattern_name, e.under_pressure, s.body_part_name, s.technique_name,
           s.shot_type_name, s.first_time, s.key_pass_event_id
    FROM shots AS s JOIN events AS e USING (event_id)
    JOIN scoped_matches AS sm USING (match_id)
    WHERE e.player_id IS NOT NULL
      AND e.team_id IS NOT NULL
      AND e.period IS NOT NULL
      AND e.location_x IS NOT NULL AND e.location_y IS NOT NULL
      AND s.body_part_name IS NOT NULL AND s.technique_name IS NOT NULL
      AND s.shot_type_name IS NOT NULL AND s.shot_type_name <> 'Penalty'
      AND e.period <> 5
), contexts AS (
    SELECT shot.*,
      (SELECT count(*) FROM events AS previous_event
       LEFT JOIN shots AS previous_shot ON previous_shot.event_id = previous_event.event_id
       WHERE previous_event.match_id = shot.match_id
         AND previous_event.event_index < shot.event_index
         AND previous_event.team_id = shot.team_id
         AND (previous_shot.outcome_name = 'Goal'
              OR previous_event.event_type_name = 'Own Goal For')) AS team_score_before,
      (SELECT count(*) FROM events AS previous_event
       LEFT JOIN shots AS previous_shot ON previous_shot.event_id = previous_event.event_id
       WHERE previous_event.match_id = shot.match_id
         AND previous_event.event_index < shot.event_index
         AND previous_event.team_id <> shot.team_id
         AND (previous_shot.outcome_name = 'Goal'
              OR previous_event.event_type_name = 'Own Goal For')) AS opponent_score_before,
      CASE WHEN shot.possession_id IS NULL THEN NULL ELSE
        (SELECT count(*) FROM events AS possession_event
         WHERE possession_event.match_id = shot.match_id
           AND possession_event.possession_id = shot.possession_id
           AND possession_event.event_index < shot.event_index)
      END AS possession_action_count_before,
      CASE WHEN shot.possession_id IS NULL OR shot.timestamp IS NULL THEN NULL ELSE
        (SELECT extract(epoch FROM (shot.timestamp - possession_start.timestamp))::double precision
         FROM events AS possession_start
         WHERE possession_start.match_id = shot.match_id
           AND possession_start.possession_id = shot.possession_id
           AND possession_start.event_index <= shot.event_index
         ORDER BY possession_start.event_index, possession_start.event_id
         LIMIT 1)
      END AS possession_duration_seconds
    FROM scoped_shots AS shot
)
SELECT event_id, match_id, competition_id, season_id, match_date, event_index, period, minute,
       second,
       location_x, location_y, play_pattern_name, under_pressure, body_part_name, technique_name,
       shot_type_name, first_time, team_score_before, opponent_score_before, possession_id,
       possession_duration_seconds, possession_action_count_before
FROM contexts ORDER BY competition_id, season_id, match_id, event_index, event_id
"""

SUPPLEMENTAL_CONTEXT_SQL = """
WITH selected_shots AS (
    SELECT e.event_id::text AS shot_id, e.match_id, e.event_index, e.possession_id,
           e.location_x AS shot_x, e.location_y AS shot_y, s.key_pass_event_id
    FROM shots AS s JOIN events AS e USING (event_id)
    WHERE e.event_id = ANY(%s::uuid[])
), preceding AS (
    SELECT DISTINCT ON (shot.shot_id) shot.shot_id, event.event_type_name,
           event.location_x, event.location_y
    FROM selected_shots AS shot JOIN events AS event
      ON event.match_id = shot.match_id AND event.possession_id = shot.possession_id
     AND event.event_index < shot.event_index
    ORDER BY shot.shot_id, event.event_index DESC
)
SELECT shot.shot_id, preceding.event_type_name, preceding.location_x, preceding.location_y,
       shot.key_pass_event_id, key_pass.event_id, key_pass.event_type_name
FROM selected_shots AS shot
LEFT JOIN preceding USING (shot_id)
LEFT JOIN events AS key_pass
  ON key_pass.event_id = shot.key_pass_event_id AND key_pass.match_id = shot.match_id
 AND key_pass.event_index < shot.event_index
ORDER BY shot.shot_id
"""

FREEZE_FRAME_SQL = """
SELECT frame.event_id::text, frame.source_order, frame.teammate, frame.position_name,
       frame.location_x, frame.location_y
FROM shot_freeze_frame_players AS frame
WHERE frame.event_id = ANY(%s::uuid[])
ORDER BY frame.event_id, frame.source_order
"""


def load_v2_contexts(
    conn: psycopg.Connection[Any], config: Mapping[str, Any]
) -> tuple[V2ContextObservation, ...]:
    """Read deterministic target-free contexts for exactly the protocol development pool.

    The query has no target projection.  The only outcome-dependent expression is the server-side
    reconstruction of scores from *strictly earlier* recorded goals; neither a current label nor
    any outcome value reaches Python or a context object.
    """
    scopes = permitted_development_scopes(config)
    names = _tournament_names(config)
    values = tuple(sorted(scopes))
    placeholders = ", ".join(["(%s, %s)"] * len(values))
    sql = CONTEXT_LOAD_SQL.replace("VALUES %s", f"VALUES {placeholders}")
    params = [part for pair in values for part in pair]
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(sql, params)
        rows = cur.fetchall()
        observations: list[V2ContextObservation] = []
        seen: set[str] = set()
        for row in rows:
            observation = _context_from_row(row, names)
            if observation.metadata.shot_id in seen:
                raise ContextLoadError(f"duplicate shot {observation.metadata.shot_id}")
            seen.add(observation.metadata.shot_id)
            observations.append(observation)
        return _attach_source_details(cur, observations)


def _attach_source_details(
    cur: psycopg.Cursor[Any], observations: list[V2ContextObservation]
) -> tuple[V2ContextObservation, ...]:
    """Attach recorded predecessor, key-pass, and freeze-frame observations without inference."""
    if not observations:
        return ()
    shot_ids = [item.metadata.shot_id for item in observations]
    by_id = {item.metadata.shot_id: item for item in observations}
    details: dict[str, tuple[object, ...]] = {}
    frames: dict[str, list[V2FreezeFrameActor]] = defaultdict(list)
    cur.execute(SUPPLEMENTAL_CONTEXT_SQL, (shot_ids,))
    for row in cur.fetchall():
        details[str(row[0])] = tuple(row[1:])
    cur.execute(FREEZE_FRAME_SQL, (shot_ids,))
    for row in cur.fetchall():
        if len(row) != 6:
            raise ContextLoadError("freeze-frame query returned an unexpected row shape")
        frames[str(row[0])].append(
            V2FreezeFrameActor(
                source_order=_required_int(row[1]),
                teammate=_required_bool(row[2]),
                position_name=_optional_str(row[3]),
                location_x=_optional_float(row[4]),
                location_y=_optional_float(row[5]),
            )
        )
    attached: list[V2ContextObservation] = []
    for shot_id, observation in by_id.items():
        preceding, key_pass_type, key_pass_length = _source_details(
            details.get(shot_id), observation.context.location_x, observation.context.location_y
        )
        context = replace(
            observation.context,
            preceding_action=preceding,
            key_pass_event_type=key_pass_type,
            key_pass_length=key_pass_length,
            freeze_frame=tuple(frames.get(shot_id, ())),
        )
        attached.append(replace(observation, context=context))
    return contexts_for_audit(attached)


def _source_details(
    row: tuple[object, ...] | None, shot_x: float, shot_y: float
) -> tuple[V2PrecedingAction | None, str | None, float | None]:
    if row is None:
        return None, None, None
    if len(row) != 6:
        raise ContextLoadError(f"supplemental context row has {len(row)} fields, expected 6")
    preceding_type = _optional_str(row[0])
    previous_x, previous_y = _optional_float(row[1]), _optional_float(row[2])
    preceding = None
    if preceding_type is not None:
        displacement = None
        if previous_x is not None and previous_y is not None:
            displacement = ((shot_x - previous_x) ** 2 + (shot_y - previous_y) ** 2) ** 0.5
        preceding = V2PrecedingAction(
            event_type_name=preceding_type,
            displacement=displacement,
            # The typed event schema records an event start location, not a universal endpoint.
            end_zone=None,
            is_supported_action=preceding_type in {"Pass", "Carry", "Dribble"},
        )
    key_pass_reference = row[3]
    resolved_key_pass = row[4]
    if key_pass_reference is None:
        if resolved_key_pass is not None or row[5] is not None:
            raise ContextLoadError("key-pass result exists without a source relation")
        key_type = None
    elif resolved_key_pass is None:
        raise ContextLoadError("key-pass relation did not resolve before the shot within its match")
    else:
        key_type = _required_str(row[5])
    # Residual key-pass JSON has not passed a typed attribute contract. Do not relabel the
    # straight-line distance from an event start to the shot as a recorded pass length.
    return preceding, key_type, None


def _context_from_row(
    row: Sequence[object], names: Mapping[tuple[int, int], str]
) -> V2ContextObservation:
    if len(row) != 22:
        raise ContextLoadError(f"context query returned {len(row)} fields, expected 22")
    try:
        (
            shot_id,
            match_id,
            competition_id,
            season_id,
            match_date,
            event_index,
            period,
            minute,
            second,
        ) = row[:9]
        location_x, location_y = _required_float(row[9]), _required_float(row[10])
        scope = (_required_int(competition_id), _required_int(season_id))
        tournament = names[scope]
    except (KeyError, TypeError, ValueError) as exc:
        raise ContextLoadError(f"malformed context row: {row!r}") from exc
    if scope in SEALED_SCOPES:
        raise SealedScopeError(f"context row includes sealed {scope} ({SEALED_SET_NAMES[scope]})")
    metadata = V2ShotMetadata(
        shot_id=_required_str(shot_id),
        match_id=_required_int(match_id),
        competition_id=scope[0],
        season_id=scope[1],
        tournament=tournament,
        match_date=_required_date(match_date),
        event_index=_required_int(event_index),
    )
    clock = (
        None
        if minute is None or second is None
        else _required_int(minute) * 60 + _required_int(second)
    )
    context = V2ShotContext(
        schema_version=CONTEXT_SCHEMA_VERSION,
        location_x=location_x,
        location_y=location_y,
        distance_to_goal=distance_to_goal(location_x, location_y),
        visible_goal_angle=visible_goal_angle(location_x, location_y),
        body_part_name=_required_str(row[13]),
        technique_name=_required_str(row[14]),
        shot_type_name=_required_str(row[15]),
        play_pattern_name=_optional_str(row[11]),
        under_pressure=_optional_bool(row[12]),
        first_time=_optional_bool(row[16]),
        period=_optional_int(period),
        minute=_optional_int(minute),
        second=_optional_int(second),
        match_clock_seconds=clock,
        team_score_before=_required_int(row[17]),
        opponent_score_before=_required_int(row[18]),
        possession_id=_optional_int(row[19]),
        possession_duration_seconds=_optional_float(row[20]),
        possession_action_count_before=_optional_int(row[21]),
        preceding_action=None,
        key_pass_event_type=None,
        key_pass_length=None,
        freeze_frame=(),
    )
    return V2ContextObservation(metadata=metadata, context=context)


def _optional_int(value: object) -> int | None:
    return None if value is None else _required_int(value)


def _optional_float(value: object) -> float | None:
    return None if value is None else _required_float(value)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return _required_str(value)


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ContextLoadError(f"expected bool or None, got {value!r}")
    return value


def _required_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise ContextLoadError(f"expected bool, got {value!r}")
    return value


def _required_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContextLoadError(f"expected integer, got {value!r}")
    return value


def _required_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContextLoadError(f"expected numeric value, got {value!r}")
    return float(value)


def _required_str(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ContextLoadError(f"expected non-empty string, got {value!r}")
    return value


def _required_date(value: object) -> dt.date:
    if not isinstance(value, dt.date):
        raise ContextLoadError(f"expected match date, got {value!r}")
    return value


def contexts_for_audit(
    observations: Iterable[V2ContextObservation],
) -> tuple[V2ContextObservation, ...]:
    """Validate canonical values and normalize the audit hand-off to deterministic order."""
    materialized = tuple(observations)
    seen: set[str] = set()
    for observation in materialized:
        metadata = observation.metadata
        scope = (metadata.competition_id, metadata.season_id)
        if scope in SEALED_SCOPES:
            raise SealedScopeError(
                f"audit observation includes sealed {scope} ({SEALED_SET_NAMES[scope]})"
            )
        expected_tournament = WP6_1_DEVELOPMENT_SCOPE_NAMES.get(scope)
        if expected_tournament is None:
            raise ContextLoadError(f"audit observation includes foreign scope {scope}")
        if metadata.tournament != expected_tournament:
            raise ContextLoadError(
                f"audit observation names {metadata.tournament!r} for {scope}, expected "
                f"{expected_tournament!r}"
            )
        if metadata.shot_id in seen:
            raise ContextLoadError(f"duplicate audit shot {metadata.shot_id}")
        seen.add(metadata.shot_id)
    ordered = tuple(
        sorted(
            materialized,
            key=lambda item: (
                item.metadata.competition_id,
                item.metadata.season_id,
                item.metadata.match_id,
                item.metadata.event_index,
                item.metadata.shot_id,
            ),
        )
    )
    assert_context_boundary(ordered)
    return ordered
