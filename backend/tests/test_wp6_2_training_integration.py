"""Isolated-schema contract for the WP6.2 authoritative development-label join."""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import date

import psycopg
import pytest
from support.db_safety import connect_local
from support.wp24_synthetic import seed_cohort

from touchline.features.geometry import distance_to_goal, visible_goal_angle
from touchline.modeling.wp6_1_context import (
    CONTEXT_SCHEMA_VERSION,
    V2ContextObservation,
    V2ShotContext,
    V2ShotMetadata,
)
from touchline.modeling.wp6_2_training import LabelJoinError, load_v2_training_rows

DB_URL = os.environ.get("TOUCHLINE_DB_URL")
SCHEMA = "wp62_training_join_test"
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(DB_URL is None, reason="TOUCHLINE_DB_URL is not set"),
]


@pytest.fixture
def conn() -> Iterator[psycopg.Connection[object]]:
    assert DB_URL is not None
    with connect_local(DB_URL) as connection:
        with connection.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
            cur.execute(f'CREATE SCHEMA "{SCHEMA}"')
            cur.execute(f'SET search_path TO "{SCHEMA}"')
        connection.commit()
        try:
            seed_cohort(connection)
            yield connection
        finally:
            connection.rollback()
            with connection.cursor() as cur:
                cur.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
            connection.commit()


def _observation(
    shot_id: str, match_id: int, comp: int, season: int, name: str, index: int
) -> V2ContextObservation:
    x, y = 100.0, 40.0
    return V2ContextObservation(
        V2ShotMetadata(shot_id, match_id, comp, season, name, date(2018, 1, 1), index),
        V2ShotContext(
            CONTEXT_SCHEMA_VERSION,
            x,
            y,
            distance_to_goal(x, y),
            visible_goal_angle(x, y),
            "Right Foot",
            "Normal",
            "Open Play",
            "Regular Play",
            None,
            None,
            1,
            1,
            1,
            61,
            0,
            0,
            1,
            1.0,
            1,
            None,
            None,
            None,
            (),
        ),
    )


def test_read_only_authoritative_join_across_all_development_scopes(
    conn: psycopg.Connection[object],
) -> None:
    rows = (
        _observation("00000000-0000-0000-0000-000000000001", 200, 43, 3, "WC2018", 1),
        _observation("00000000-0000-0000-0000-000000000011", 205, 55, 43, "Euro2020", 1),
        _observation("00000000-0000-0000-0000-000000000081", 230, 43, 106, "WC2022", 1),
        _observation("00000000-0000-0000-0000-000000000082", 240, 55, 282, "Euro2024", 1),
    )
    joined = load_v2_training_rows(conn, rows)
    assert [item.observation.metadata.shot_id for item in joined] == [
        item.metadata.shot_id for item in rows
    ]
    assert [item.is_goal for item in joined] == [1, 1, 0, 1]
    with pytest.raises(LabelJoinError, match="duplicate"):
        load_v2_training_rows(conn, (rows[0], rows[0]))
    missing = replace(
        rows[0],
        metadata=replace(
            rows[0].metadata,
            shot_id="00000000-0000-0000-0000-999999999999",
        ),
    )
    with pytest.raises(LabelJoinError, match="missing"):
        load_v2_training_rows(conn, (missing, *rows[1:]))
    foreign = _observation(rows[0].metadata.shot_id, 200, 999, 1, "Foreign", 1)
    with pytest.raises(LabelJoinError, match="foreign"):
        load_v2_training_rows(conn, (foreign,))
    sealed = _observation(rows[0].metadata.shot_id, 200, 1267, 107, "AFCON 2023", 1)
    with pytest.raises(LabelJoinError, match="foreign"):
        load_v2_training_rows(conn, (sealed,))
