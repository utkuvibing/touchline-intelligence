"""Focused target-free contracts for the WP6.1 context seam."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import replace

import pytest

from touchline.features.geometry import distance_to_goal, visible_goal_angle
from touchline.ingest.parse import parse_events
from touchline.modeling.v2_folds import load_gate_config
from touchline.modeling.wp6_1_context import (
    CONTEXT_SCHEMA_VERSION,
    ContextBoundaryError,
    ContextLoadError,
    V2FreezeFrameActor,
    V2PrecedingAction,
    V2ShotContext,
    V2ShotMetadata,
    assert_context_boundary,
    contexts_for_audit,
    load_v2_contexts,
    permitted_development_scopes,
)
from touchline.modeling.wp6_1_labels import V2TrainingExample
from touchline.sealed_scope import SealedScopeError


def _context() -> V2ShotContext:
    return V2ShotContext(
        schema_version=CONTEXT_SCHEMA_VERSION,
        location_x=100.0,
        location_y=40.0,
        distance_to_goal=distance_to_goal(100.0, 40.0),
        visible_goal_angle=visible_goal_angle(100.0, 40.0),
        body_part_name="Right Foot",
        technique_name="Normal",
        shot_type_name="Open Play",
        play_pattern_name="Regular Play",
        under_pressure=None,
        first_time=None,
        period=1,
        minute=3,
        second=4,
        match_clock_seconds=184,
        team_score_before=0,
        opponent_score_before=0,
        possession_id=1,
        possession_duration_seconds=2.0,
        possession_action_count_before=1,
        preceding_action=None,
        key_pass_event_type=None,
        key_pass_length=None,
        freeze_frame=(),
    )


def test_context_has_no_residual_mapping_for_provider_xg() -> None:
    context = _context()
    assert not hasattr(context, "statsbomb_xg")
    with pytest.raises(ContextBoundaryError, match="provider xG"):
        assert_context_boundary({"raw": {"statsbomb_xg": 0.4}})
    with pytest.raises(ContextBoundaryError, match="provider xG"):
        assert_context_boundary({"derived_feature_name": "xg"})


def test_upstream_provider_xg_is_quarantined_but_canonical_propagation_fails() -> None:
    raw_event = {
        "id": "event-a",
        "index": 4,
        "period": 1,
        "minute": 12,
        "second": 3,
        "type": {"id": 30, "name": "Pass"},
        "team": {"id": 7001, "name": "Fixture United"},
        "pass": {"height": {"id": 1, "name": "Ground Pass"}, "statsbomb_xg": 0.9},
    }

    events, _, _, _, _, _ = parse_events(900001, [raw_event])

    assert events[0].type_data == {"pass": {"height": {"id": 1, "name": "Ground Pass"}}}
    with pytest.raises(ContextBoundaryError, match="provider xG"):
        assert_context_boundary(raw_event)


def test_context_rejects_geometry_that_does_not_match_source_location() -> None:
    with pytest.raises(ContextBoundaryError, match="distance_to_goal"):
        replace(_context(), distance_to_goal=19.0)


def test_context_rejects_unverified_normalized_values() -> None:
    preceding = V2PrecedingAction("Pass", 10.0, "central", True)
    with pytest.raises(ContextBoundaryError, match="end zone"):
        replace(_context(), preceding_action=preceding)
    with pytest.raises(ContextBoundaryError, match="key-pass length"):
        replace(_context(), key_pass_length=12.0)


def test_freeze_frame_actor_rejects_partial_or_out_of_bounds_coordinates() -> None:
    with pytest.raises(ContextBoundaryError, match="both be present"):
        V2FreezeFrameActor(1, False, "Goalkeeper", 118.0, None)
    with pytest.raises(ContextBoundaryError, match="outside"):
        V2FreezeFrameActor(1, False, "Goalkeeper", 121.0, 40.0)


def test_future_training_example_keeps_the_label_outside_context() -> None:
    example = V2TrainingExample(context=_context(), is_goal=1)
    assert example.is_goal == 1
    assert not hasattr(example.context, "is_goal")
    with pytest.raises(ValueError, match="0 or 1"):
        V2TrainingExample(context=_context(), is_goal=2)
    with pytest.raises(TypeError, match="V2ShotContext"):
        V2TrainingExample(context={"xg": 0.4}, is_goal=1)  # type: ignore[arg-type]


def test_context_metadata_can_supply_fold_match_facts_without_identity_features() -> None:
    metadata = V2ShotMetadata("a", 1, 43, 3, "WC2018", dt.date(2018, 6, 14), 2)
    assert metadata.match_date == dt.date(2018, 6, 14)
    assert _context().body_part_name == "Right Foot"


def test_audit_handoff_is_deterministic_and_rechecks_boundary() -> None:
    from touchline.modeling.wp6_1_context import V2ContextObservation

    observation = V2ContextObservation(
        V2ShotMetadata("b", 2, 43, 3, "WC2018", dt.date(2018, 6, 14), 2), _context()
    )
    assert contexts_for_audit([observation]) == (observation,)

    with pytest.raises(ContextLoadError, match="duplicate audit shot"):
        contexts_for_audit([observation, observation])
    sealed = replace(
        observation,
        metadata=replace(
            observation.metadata,
            competition_id=1267,
            season_id=107,
            tournament="AFCON 2023",
        ),
    )
    with pytest.raises(SealedScopeError, match="sealed"):
        contexts_for_audit([sealed])
    foreign = replace(
        observation,
        metadata=replace(
            observation.metadata, competition_id=999, season_id=999, tournament="Foreign"
        ),
    )
    with pytest.raises(ContextLoadError, match="foreign scope"):
        contexts_for_audit([foreign])


def test_exact_four_unsealed_development_scopes_are_required() -> None:
    assert permitted_development_scopes(load_gate_config()) == {
        (43, 3),
        (55, 43),
        (43, 106),
        (55, 282),
    }


def test_foreign_development_scope_is_rejected() -> None:
    config = {
        "development_pool": [
            {"name": "Foreign", "competition_id": 999, "season_id": 999},
            {"name": "Euro2020", "competition_id": 55, "season_id": 43},
            {"name": "WC2022", "competition_id": 43, "season_id": 106},
            {"name": "Euro2024", "competition_id": 55, "season_id": 282},
        ]
    }
    with pytest.raises(ContextLoadError, match="exactly WC 2018"):
        permitted_development_scopes(config)


class _Transaction(AbstractContextManager[None]):
    def __enter__(self) -> None:
        return None

    def __exit__(self, *args: object) -> None:
        return None


class _Cursor(AbstractContextManager["_Cursor"]):
    def __init__(self, results: list[list[tuple[object, ...]]]) -> None:
        self._results = iter(results)
        self._current: list[tuple[object, ...]] = []
        self.executed: list[str] = []

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: object = None) -> None:
        self.executed.append(sql)
        if not sql.startswith("SET TRANSACTION"):
            self._current = next(self._results)

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._current


class _Connection:
    def __init__(self, cursors: list[_Cursor]) -> None:
        self._cursors: Iterator[_Cursor] = iter(cursors)
        self.used: list[_Cursor] = []

    def transaction(self) -> _Transaction:
        return _Transaction()

    def cursor(self) -> _Cursor:
        cursor = next(self._cursors)
        self.used.append(cursor)
        return cursor


def _base_row(
    *,
    shot_id: str = "00000000-0000-0000-0000-000000000001",
    possession_id: int | None = 2,
    possession_duration: float | None = 3.5,
    possession_action_count: int | None = 4,
    event_index: int = 20,
    under_pressure: bool | None = None,
    first_time: bool | None = None,
) -> tuple[object, ...]:
    return (
        shot_id,
        1,
        43,
        3,
        dt.date(2018, 6, 14),
        event_index,
        1,
        3,
        4,
        100.0,
        40.0,
        "Regular Play",
        under_pressure,
        "Right Foot",
        "Normal",
        "Open Play",
        first_time,
        1,
        0,
        possession_id,
        possession_duration,
        possession_action_count,
    )


def test_loader_preserves_source_facts_and_never_invents_unsupported_values() -> None:
    shot_id = str(_base_row()[0])
    cursor = _Cursor(
        [
            [_base_row()],
            [(shot_id, "Pass", 90.0, 40.0, "key-pass-id", "key-pass-id", "Pass")],
            [(shot_id, 1, False, "Goalkeeper", 118.0, 40.0)],
        ]
    )
    conn = _Connection([cursor])

    observations = load_v2_contexts(conn, load_gate_config())  # type: ignore[arg-type]

    assert len(observations) == 1
    context = observations[0].context
    assert context.team_score_before == 1
    assert context.opponent_score_before == 0
    assert context.preceding_action is not None
    assert context.preceding_action.displacement == 10.0
    assert context.preceding_action.end_zone is None
    assert context.key_pass_event_type == "Pass"
    assert context.key_pass_length is None
    assert context.freeze_frame[0].teammate is False
    assert cursor.executed[0] == "SET TRANSACTION READ ONLY"
    assert sum(sql == "SET TRANSACTION READ ONLY" for sql in cursor.executed) == 1


def test_loader_keeps_false_distinct_from_missing_sparse_flags() -> None:
    false_id = "00000000-0000-0000-0000-000000000001"
    missing_id = "00000000-0000-0000-0000-000000000002"
    cursor = _Cursor(
        [
            [
                _base_row(
                    shot_id=false_id,
                    event_index=20,
                    under_pressure=False,
                    first_time=False,
                ),
                _base_row(shot_id=missing_id, event_index=21),
            ],
            [
                (false_id, None, None, None, None, None, None),
                (missing_id, None, None, None, None, None, None),
            ],
            [],
        ]
    )

    observations = load_v2_contexts(
        _Connection([cursor]),  # type: ignore[arg-type]
        load_gate_config(),
    )
    by_id = {item.metadata.shot_id: item.context for item in observations}

    assert by_id[false_id].under_pressure is False
    assert by_id[false_id].first_time is False
    assert by_id[missing_id].under_pressure is None
    assert by_id[missing_id].first_time is None


def test_loader_rejects_malformed_freeze_frame_boolean() -> None:
    shot_id = str(_base_row()[0])
    conn = _Connection(
        [
            _Cursor(
                [
                    [_base_row()],
                    [(shot_id, None, None, None, None, None, None)],
                    [(shot_id, 1, None, "Goalkeeper", 118.0, 40.0)],
                ]
            ),
        ]
    )
    with pytest.raises(ValueError, match="expected bool"):
        load_v2_contexts(conn, load_gate_config())  # type: ignore[arg-type]


def test_loader_rejects_an_unresolved_key_pass_relation() -> None:
    shot_id = str(_base_row()[0])
    conn = _Connection(
        [
            _Cursor(
                [
                    [_base_row()],
                    [(shot_id, None, None, None, "missing-key-pass-id", None, None)],
                    [],
                ]
            ),
        ]
    )
    with pytest.raises(ContextLoadError, match="key-pass relation"):
        load_v2_contexts(conn, load_gate_config())  # type: ignore[arg-type]


def test_loader_preserves_missing_possession_facts_and_rejects_negative_duration() -> None:
    shot_id = str(_base_row()[0])
    missing = _Cursor(
        [
            [
                _base_row(
                    possession_id=None,
                    possession_duration=None,
                    possession_action_count=None,
                )
            ],
            [(shot_id, None, None, None, None, None, None)],
            [],
        ]
    )
    observation = load_v2_contexts(
        _Connection([missing]),  # type: ignore[arg-type]
        load_gate_config(),
    )[0]
    assert observation.context.possession_id is None
    assert observation.context.possession_duration_seconds is None
    assert observation.context.possession_action_count_before is None

    non_monotonic = _Cursor(
        [
            [_base_row(possession_duration=-1.0)],
            [(shot_id, None, None, None, None, None, None)],
            [],
        ]
    )
    with pytest.raises(ContextBoundaryError, match="duration must be nonnegative"):
        load_v2_contexts(_Connection([non_monotonic]), load_gate_config())  # type: ignore[arg-type]


def test_context_sql_uses_exact_eligible_cohort_and_pre_shot_score_rules() -> None:
    from touchline.modeling.wp6_1_context import CONTEXT_LOAD_SQL, SUPPLEMENTAL_CONTEXT_SQL

    for clause in (
        "s.shot_type_name <> 'Penalty'",
        "e.period <> 5",
        "previous_event.event_index < shot.event_index",
        "previous_event.event_type_name = 'Own Goal For'",
        "shot.timestamp - possession_start.timestamp",
        "::double precision",
        "ORDER BY possession_start.event_index, possession_start.event_id",
        "CASE WHEN shot.possession_id IS NULL THEN NULL",
        "shot.possession_id IS NULL OR shot.timestamp IS NULL",
    ):
        assert clause in CONTEXT_LOAD_SQL
    assert "Own Goal Against" not in CONTEXT_LOAD_SQL
    assert "home_score" not in CONTEXT_LOAD_SQL
    assert "away_score" not in CONTEXT_LOAD_SQL
    scoped_shots = CONTEXT_LOAD_SQL.split("), contexts AS", maxsplit=1)[0]
    assert "outcome_name" not in scoped_shots
    assert "key_pass.event_index < shot.event_index" in SUPPLEMENTAL_CONTEXT_SQL
