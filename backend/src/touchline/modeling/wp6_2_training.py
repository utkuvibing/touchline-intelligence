"""Explicit, read-only development-label seam for WP6.2."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

from touchline.modeling.v2_folds import load_gate_config
from touchline.modeling.wp6_1_context import (
    WP6_1_DEVELOPMENT_SCOPE_NAMES,
    V2ContextObservation,
    V2ShotContext,
    V2ShotMetadata,
    assert_context_boundary,
    permitted_development_scopes,
)

ROOT = Path(__file__).resolve().parents[4]
COHORT_SQL_PATH = ROOT / "backend/sql/wp2_1/01_model_shot_cohort.sql"
COHORT_SQL_SHA256 = "301d8a620b60d8da6011c7c4d12ef8108c658df4d923f612c3e3bf9e0427978e"


class LabelJoinError(ValueError):
    """The authoritative WP2.1 labels cannot be joined safely."""


@dataclass(frozen=True, slots=True)
class V2TrainingRow:
    observation: V2ContextObservation
    is_goal: int

    def __post_init__(self) -> None:
        if not isinstance(self.observation, V2ContextObservation):
            raise TypeError("V2TrainingRow observation must be a V2ContextObservation")
        if not isinstance(self.observation.context, V2ShotContext) or not isinstance(
            self.observation.metadata, V2ShotMetadata
        ):
            raise TypeError("V2TrainingRow requires a complete WP6.1 observation")
        assert_context_boundary(self.observation.context)
        scope = (
            self.observation.metadata.competition_id,
            self.observation.metadata.season_id,
        )
        if (
            scope not in WP6_1_DEVELOPMENT_SCOPE_NAMES
            or self.observation.metadata.tournament != WP6_1_DEVELOPMENT_SCOPE_NAMES[scope]
        ):
            raise LabelJoinError("V2TrainingRow scope must be a named development tournament")
        if isinstance(self.is_goal, bool) or not isinstance(self.is_goal, int):
            raise LabelJoinError("is_goal must be an integer binary target")
        if self.is_goal not in (0, 1):
            raise LabelJoinError("is_goal must be binary")


def verified_cohort_sql() -> str:
    data = COHORT_SQL_PATH.read_bytes()
    if b"\r" in data or hashlib.sha256(data).hexdigest() != COHORT_SQL_SHA256:
        raise LabelJoinError("WP2.1 cohort SQL byte verification failed")
    return data.decode("utf-8").rstrip().rstrip(";")


def load_v2_training_rows(
    conn: psycopg.Connection[Any],
    observations: Sequence[V2ContextObservation],
    config: Mapping[str, Any] | None = None,
) -> tuple[V2TrainingRow, ...]:
    if len(observations) == 0:
        raise LabelJoinError("cannot load labels for an empty observation sequence")
    config = load_gate_config() if config is None else config
    allowed = permitted_development_scopes(config)
    ids, seen = [], set()
    for item in observations:
        if not isinstance(item, V2ContextObservation):
            raise LabelJoinError("labels can only join V2ContextObservation values")
        if not isinstance(item.context, V2ShotContext) or not isinstance(
            item.metadata, V2ShotMetadata
        ):
            raise LabelJoinError("labels can only join complete WP6.1 observations")
        assert_context_boundary(item.context)
        if item.metadata.shot_id in seen:
            raise LabelJoinError("duplicate supplied shot")
        if not isinstance(item.metadata.shot_id, str) or not item.metadata.shot_id:
            raise LabelJoinError("supplied shot IDs must be non-empty strings")
        seen.add(item.metadata.shot_id)
        ids.append(item.metadata.shot_id)
        scope = (item.metadata.competition_id, item.metadata.season_id)
        if scope not in allowed or scope not in WP6_1_DEVELOPMENT_SCOPE_NAMES:
            raise LabelJoinError("foreign or sealed observation scope")
        if item.metadata.tournament != WP6_1_DEVELOPMENT_SCOPE_NAMES[scope]:
            raise LabelJoinError("observation tournament does not match its protocol scope")
    sql = (
        "SELECT shot_id::text, is_goal FROM "
        f"({verified_cohort_sql()}) AS cohort WHERE shot_id::text = ANY(%s::text[])"
    )
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(sql, (ids,))
        rows = cur.fetchall()
    labels: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, Sequence) or len(row) != 2:
            raise LabelJoinError("label query returned an unexpected row shape")
        shot_id, is_goal = row
        key = str(shot_id)
        if key not in seen:
            raise LabelJoinError("extra or foreign label row")
        if key in labels:
            raise LabelJoinError("duplicate label row")
        if isinstance(is_goal, bool) or not isinstance(is_goal, int):
            raise LabelJoinError("non-binary label row")
        if is_goal not in (0, 1):
            raise LabelJoinError("non-binary label row")
        labels[key] = int(is_goal)
    if set(labels) != seen:
        raise LabelJoinError("missing label rows")
    return tuple(V2TrainingRow(item, labels[item.metadata.shot_id]) for item in observations)
