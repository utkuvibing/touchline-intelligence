"""Opt-in, read-only full-cohort acceptance for the WP6.2 feature seam."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from support.db_safety import connect_local

from touchline.modeling.v2_folds import load_gate_config
from touchline.modeling.wp6_1_context import load_v2_contexts
from touchline.modeling.wp6_2_features import (
    fit_v2_transformer,
    load_v2_transformer,
    save_v2_transformer,
)
from touchline.modeling.wp6_2_training import load_v2_training_rows
from touchline.validation_tiers import is_local_postgres_url

DB_URL = os.environ.get("TOUCHLINE_FULL_COHORT_DB_URL")
EXPECTED_BY_TOURNAMENT = {
    "WC2018": 1638,
    "Euro2020": 1234,
    "WC2022": 1430,
    "Euro2024": 1304,
}

pytestmark = [
    pytest.mark.integration,
    pytest.mark.full_cohort,
    pytest.mark.skipif(
        DB_URL is None,
        reason="TOUCHLINE_FULL_COHORT_DB_URL is not set for the 5,606-row WP6.2 acceptance",
    ),
]


def _matrix_digest(matrix: object) -> str:
    values = matrix.values  # type: ignore[attr-defined]
    columns = matrix.columns  # type: ignore[attr-defined]
    shot_ids = matrix.shot_ids  # type: ignore[attr-defined]
    payload = {
        "columns": list(columns),
        "shot_ids": list(shot_ids),
        "shape": list(values.shape),
        "dtype": str(values.dtype),
    }
    digest = hashlib.sha256()
    digest.update(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    digest.update(values.tobytes(order="C"))
    return digest.hexdigest()


def test_full_cohort_feature_matrices_and_label_join_are_deterministic(
    tmp_path: Path,
) -> None:
    assert DB_URL is not None
    assert is_local_postgres_url(DB_URL), "full-cohort WP6.2 acceptance refuses deployed databases"
    config = load_gate_config()
    with connect_local(DB_URL, connect_timeout=15) as conn:
        conn.read_only = True
        observations = load_v2_contexts(conn, config)
        training_rows = load_v2_training_rows(conn, observations, config)

    assert len(observations) == 5606
    assert len(training_rows) == 5606
    assert {row.is_goal for row in training_rows} <= {0, 1}
    assert {
        tournament: sum(item.metadata.tournament == tournament for item in observations)
        for tournament in EXPECTED_BY_TOURNAMENT
    } == EXPECTED_BY_TOURNAMENT

    f0 = fit_v2_transformer(observations, "F0")
    f1 = fit_v2_transformer(observations, "F1")
    first_f0, first_f1 = f0.transform(observations), f1.transform(observations)
    f0_again = fit_v2_transformer(observations, "F0")
    f1_again = fit_v2_transformer(observations, "F1")
    second_f0, second_f1 = f0_again.transform(observations), f1_again.transform(observations)
    assert _matrix_digest(first_f0) == _matrix_digest(second_f0)
    assert _matrix_digest(first_f1) == _matrix_digest(second_f1)
    assert f0.fit_identity_digest == f0_again.fit_identity_digest
    assert f1.fit_identity_digest == f1_again.fit_identity_digest

    pickle_path, manifest_path = tmp_path / "f1.pkl", tmp_path / "f1.json"
    save_v2_transformer(f1, pickle_path, manifest_path)
    reloaded = load_v2_transformer(pickle_path, manifest_path)
    reloaded_matrix = reloaded.transform(observations)
    assert _matrix_digest(first_f1) == _matrix_digest(reloaded_matrix)
