"""Unit contracts for the WP2.4 stable inference artifact (blocking corrections P0/P1).

Covers:

- the persisted class identity is ``touchline.modeling.artifact.ArtifactBundle`` (never bound to an
  executable ``__main__`` module) and the artifact schema version is pinned;
- ``load_bundle`` round-trips a real bundle and ``infer`` scores raw rows with persisted
  preprocessing, never a re-fit;
- every feature-contract mismatch raises the specific ``ArtifactCompatibilityError`` — reordered
  columns, missing/unexpected columns, duplicated names, selected-name/index disagreement,
  estimator feature-count mismatch, and an unsupported schema version — never a silent probability
  or a bare generic ValueError;
- ``load_bundle`` refuses non-bundle pickles.
"""

from __future__ import annotations

import pickle
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from touchline.modeling.artifact import (
    ArtifactBundle,
    ArtifactCompatibilityError,
    artifact_schema_version,
    infer,
    load_bundle,
)
from touchline.modeling.logistic import fit_logistic
from touchline.modeling.preprocessing import ShotRow, encode_rows, fit_scaler
from touchline.modeling.train import build_vocabulary


def _rows() -> list[ShotRow]:
    rng = np.random.default_rng(5)
    rows: list[ShotRow] = []
    for fold in range(5):
        for i in range(12):
            y = 1 if i < 6 else 0
            rows.append(
                ShotRow(
                    shot_id=f"a{fold}-{i}",
                    match_id=300 + fold,
                    fold=fold,
                    competition_id=43,
                    season_id=3,
                    y=y,
                    distance_to_goal=20.0 + float(rng.normal()),
                    visible_goal_angle=0.3 + 0.02 * float(rng.normal()),
                    body_part_name="Right Foot",
                    technique_name="Normal",
                    play_pattern_name="Regular Play",
                    first_time=None,
                    under_pressure=None,
                )
            )
    return rows


def _make_bundle() -> tuple[ArtifactBundle, list[ShotRow], list[int]]:
    rows = _rows()
    vocabulary = build_vocabulary(rows)
    scaler = fit_scaler(rows)
    all_columns = vocabulary.column_names()
    selected_indices = [i for i in range(len(all_columns)) if i not in (2, 3)]
    full, _ = encode_rows(rows, vocabulary, scaler)
    y = np.asarray([row.y for row in rows], dtype=np.int_)
    estimator = fit_logistic(full[:, selected_indices], y, 0.1).estimator
    bundle = ArtifactBundle(
        schema_version=artifact_schema_version,
        experiment_id="unit",
        shipped_candidate="full_minus_presence",
        best_c=0.1,
        code_commit="c",
        reproduction_commit="c",
        data_source_commit="d",
        cohort_sql_sha256="0" * 64,
        assignments_sha256="0" * 64,
        input_config_sha256="0" * 64,
        uv_lock_sha256="0" * 64,
        estimator=estimator,
        scaler=scaler,
        vocabulary=vocabulary,
        all_columns=tuple(all_columns),
        selected_columns=tuple(all_columns[i] for i in selected_indices),
        selected_indices=tuple(selected_indices),
        reference_levels=dict(vocabulary.reference),
        rare_mapping={field: tuple(levels) for field, levels in vocabulary.rare_members.items()},
    )
    return bundle, rows, selected_indices


def test_artifact_identity_is_the_importable_module() -> None:
    assert artifact_schema_version == 1
    assert ArtifactBundle.__module__ == "touchline.modeling.artifact"
    assert ArtifactBundle.__qualname__ == "ArtifactBundle"


def test_load_bundle_round_trip_and_infer_scores_raw_rows(tmp_path: Path) -> None:
    bundle, rows, _ = _make_bundle()
    path = tmp_path / "model.pkl"
    path.write_bytes(pickle.dumps(bundle, protocol=5))
    loaded = load_bundle(path)
    assert isinstance(loaded, ArtifactBundle)
    assert type(loaded).__module__ == "touchline.modeling.artifact"
    query = rows[:6]
    probabilities = infer(loaded, query)
    assert probabilities.shape == (6,)
    assert np.isfinite(probabilities).all()
    assert ((probabilities >= 0.0) & (probabilities <= 1.0)).all()
    # Persisted-preprocessing equivalence (no re-fit at inference): predict equals encode+slice.
    full, _ = encode_rows(query, loaded.vocabulary, loaded.scaler)
    expected = loaded.estimator.predict_proba(full[:, list(loaded.selected_indices)])[:, 1]
    assert np.array_equal(probabilities, expected)


def test_load_bundle_rejects_a_non_bundle_pickle(tmp_path: Path) -> None:
    path = tmp_path / "not-a-bundle.pkl"
    path.write_bytes(pickle.dumps({"estimator": "loose", "nested": True}, protocol=5))
    with pytest.raises(ArtifactCompatibilityError):
        load_bundle(path)


def test_reordered_column_schema_raises() -> None:
    bundle, rows, _ = _make_bundle()
    tampered = replace(bundle, all_columns=tuple(reversed(bundle.all_columns)))
    with pytest.raises(ArtifactCompatibilityError):
        tampered.predict_proba(rows[:6])


def test_missing_persisted_column_raises() -> None:
    bundle, rows, _ = _make_bundle()
    tampered = replace(bundle, all_columns=(*bundle.all_columns, "synthetic_extra"))
    with pytest.raises(ArtifactCompatibilityError):
        tampered.predict_proba(rows[:6])


def test_unexpected_encoder_column_raises() -> None:
    bundle, rows, _ = _make_bundle()
    tampered = replace(bundle, all_columns=bundle.all_columns[:-1])
    with pytest.raises(ArtifactCompatibilityError):
        tampered.predict_proba(rows[:6])


def test_duplicated_persisted_column_raises() -> None:
    bundle, rows, _ = _make_bundle()
    tampered = replace(bundle, all_columns=bundle.all_columns[:1] + bundle.all_columns)
    with pytest.raises(ArtifactCompatibilityError):
        tampered.predict_proba(rows[:6])


def test_selected_column_index_disagreement_raises() -> None:
    bundle, rows, _ = _make_bundle()
    wrong_selected = tuple(reversed(bundle.selected_columns))
    tampered = replace(bundle, selected_columns=wrong_selected)
    with pytest.raises(ArtifactCompatibilityError):
        tampered.predict_proba(rows[:6])


def test_estimator_feature_count_mismatch_raises() -> None:
    bundle, rows, _ = _make_bundle()
    # An estimator fitted on exactly one feature cannot match a multi-feature selection.
    y = np.asarray([row.y for row in rows], dtype=np.int_)
    single_feature = fit_logistic(np.zeros((len(rows), 1)), y, 0.1).estimator
    tampered = replace(bundle, estimator=single_feature)
    with pytest.raises(ArtifactCompatibilityError):
        tampered.predict_proba(rows[:6])


def test_unsupported_schema_version_raises_on_predict_and_load(tmp_path: Path) -> None:
    bundle, rows, _ = _make_bundle()
    old_bundle = replace(bundle, schema_version=99)
    with pytest.raises(ArtifactCompatibilityError):
        old_bundle.predict_proba(rows[:6])
    path = tmp_path / "old.pkl"
    path.write_bytes(pickle.dumps(old_bundle, protocol=5))
    with pytest.raises(ArtifactCompatibilityError):
        load_bundle(path)
