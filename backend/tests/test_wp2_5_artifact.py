"""Unit contracts for the WP2.5 boosting inference artifact.

The boosting bundle is a **separate class** from ``ArtifactBundle`` with its own schema version.
That separation is load-bearing rather than cosmetic: adding a field to the logistic bundle, or
bumping a shared version, would change its pickled bytes and make the ``model_pickle_sha256``
published in WP2.4's evidence report unreproducible. The first test below is what holds that line.

Everything else mirrors ``test_wp2_4_artifact.py`` case for case, because the two bundles share one
validator (``artifact.validate_column_contract``) and a shared validator must be proved on both
callers — otherwise a check could be silently weakened for the family whose tests do not cover it.
"""

from __future__ import annotations

import pickle
from dataclasses import fields, replace
from pathlib import Path

import numpy as np
import pytest

from touchline.modeling.artifact import (
    ArtifactBundle,
    ArtifactCompatibilityError,
    BoostingBundle,
    artifact_schema_version,
    boosting_artifact_schema_version,
    infer_boosting,
    load_boosting_bundle,
    load_bundle,
)
from touchline.modeling.boosting import BoostingParams, fit_boosting
from touchline.modeling.preprocessing import ShotRow, encode_rows, fit_scaler
from touchline.modeling.train_boosting import build_vocabulary

PARAMS = BoostingParams(learning_rate=0.1, max_leaf_nodes=7, min_samples_leaf=20)

#: The WP2.4 logistic bundle's field list, as published. Pinned here so a WP2.5 change that adds a
#: field to the wrong class fails immediately and loudly.
WP24_BUNDLE_FIELDS = (
    "schema_version",
    "experiment_id",
    "shipped_candidate",
    "best_c",
    "code_commit",
    "reproduction_commit",
    "data_source_commit",
    "cohort_sql_sha256",
    "assignments_sha256",
    "input_config_sha256",
    "uv_lock_sha256",
    "estimator",
    "scaler",
    "vocabulary",
    "all_columns",
    "selected_columns",
    "selected_indices",
    "reference_levels",
    "rare_mapping",
)


def _rows() -> list[ShotRow]:
    rng = np.random.default_rng(5)
    rows: list[ShotRow] = []
    bodies = ("Right Foot", "Left Foot", "Head")
    for fold in range(5):
        for i in range(24):
            y = 1 if i < 8 else 0
            rows.append(
                ShotRow(
                    shot_id=f"b{fold}-{i}",
                    match_id=300 + fold,
                    fold=fold,
                    competition_id=43,
                    season_id=3,
                    y=y,
                    distance_to_goal=20.0 - 3.0 * y + float(rng.normal()),
                    visible_goal_angle=0.3 + 0.1 * y + 0.02 * float(rng.normal()),
                    body_part_name=bodies[i % len(bodies)],
                    technique_name="Normal",
                    play_pattern_name="Regular Play",
                    first_time=None,
                    under_pressure=None,
                )
            )
    return rows


def _make_bundle() -> tuple[BoostingBundle, list[ShotRow], list[int]]:
    rows = _rows()
    vocabulary = build_vocabulary(rows)
    scaler = fit_scaler(rows)
    all_columns = vocabulary.column_names()
    selected_indices = [i for i in range(len(all_columns)) if i not in (2, 3)]
    full, _ = encode_rows(rows, vocabulary, scaler)
    y = np.asarray([row.y for row in rows], dtype=np.int_)
    estimator = fit_boosting(full[:, selected_indices], y, PARAMS).estimator
    bundle = BoostingBundle(
        schema_version=boosting_artifact_schema_version,
        experiment_id="unit",
        shipped_candidate="hist_gbm",
        hyperparameters={k: float(v) for k, v in PARAMS.as_dict().items()},
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


def test_wp2_4_artifact_is_untouched_by_wp2_5() -> None:
    """WP2.5 must not perturb the logistic bundle: its pickled bytes are published evidence.

    ``ArtifactBundle``'s field list and schema version are the two things whose change would alter
    ``model_pickle_sha256`` in WP2.4's committed record and break its recreation command.
    """
    assert artifact_schema_version == 1
    assert tuple(f.name for f in fields(ArtifactBundle)) == WP24_BUNDLE_FIELDS
    assert ArtifactBundle.__module__ == "touchline.modeling.artifact"


def test_boosting_artifact_identity_and_its_own_schema_version() -> None:
    assert boosting_artifact_schema_version == 1
    assert BoostingBundle.__module__ == "touchline.modeling.artifact"
    assert BoostingBundle.__qualname__ == "BoostingBundle"


def test_load_round_trip_and_infer_scores_raw_rows(tmp_path: Path) -> None:
    bundle, rows, _ = _make_bundle()
    path = tmp_path / "model.pkl"
    path.write_bytes(pickle.dumps(bundle, protocol=5))
    loaded = load_boosting_bundle(path)
    assert isinstance(loaded, BoostingBundle)
    assert type(loaded).__module__ == "touchline.modeling.artifact"
    query = rows[:6]
    probabilities = infer_boosting(loaded, query)
    assert probabilities.shape == (6,)
    assert np.isfinite(probabilities).all()
    assert ((probabilities >= 0.0) & (probabilities <= 1.0)).all()
    # Persisted-preprocessing equivalence (no re-fit at inference): predict equals encode+slice.
    full, _ = encode_rows(query, loaded.vocabulary, loaded.scaler)
    expected = loaded.estimator.predict_proba(full[:, list(loaded.selected_indices)])[:, 1]
    assert np.array_equal(probabilities, expected)


def test_the_two_bundle_families_cannot_be_confused(tmp_path: Path) -> None:
    """A boosting pickle is not a logistic pickle and vice versa; both loaders say so."""
    bundle, _rows, _ = _make_bundle()
    path = tmp_path / "boosting.pkl"
    path.write_bytes(pickle.dumps(bundle, protocol=5))
    with pytest.raises(ArtifactCompatibilityError):
        load_bundle(path)


def test_load_rejects_a_non_bundle_pickle(tmp_path: Path) -> None:
    path = tmp_path / "not-a-bundle.pkl"
    path.write_bytes(pickle.dumps({"estimator": "loose", "nested": True}, protocol=5))
    with pytest.raises(ArtifactCompatibilityError):
        load_boosting_bundle(path)


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
    tampered = replace(bundle, selected_columns=tuple(reversed(bundle.selected_columns)))
    with pytest.raises(ArtifactCompatibilityError):
        tampered.predict_proba(rows[:6])


def test_negative_selected_index_raises_instead_of_wrapping_around() -> None:
    """A negative index must be refused, not silently wrapped to a different column.

    As in WP2.4, the tampered bundle is built so that *every other* check passes — the persisted
    names genuinely match the wrapped indices — which is what makes this a test of the bounds check
    rather than of the name/index agreement check.
    """
    bundle, rows, _ = _make_bundle()
    all_columns = bundle.all_columns
    wrapped_name = all_columns[-1]
    assert wrapped_name != all_columns[1], "fixture must keep the wrapped name distinct"
    tampered = replace(
        bundle,
        selected_indices=(-1, 1),
        selected_columns=(wrapped_name, all_columns[1]),
    )
    with pytest.raises(ArtifactCompatibilityError) as excinfo:
        tampered.predict_proba(rows[:6])
    assert "selected_indices" in str(excinfo.value)


def test_out_of_range_selected_index_raises_artifact_error_not_index_error() -> None:
    bundle, rows, _ = _make_bundle()
    tampered = replace(bundle, selected_indices=(len(bundle.all_columns), 1))
    with pytest.raises(ArtifactCompatibilityError) as excinfo:
        tampered.predict_proba(rows[:6])
    assert "selected_indices" in str(excinfo.value)
    assert not isinstance(excinfo.value, IndexError)


def test_estimator_feature_count_mismatch_raises() -> None:
    bundle, rows, _ = _make_bundle()
    y = np.asarray([row.y for row in rows], dtype=np.int_)
    single_feature = fit_boosting(np.zeros((len(rows), 1)), y, PARAMS).estimator
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
        load_boosting_bundle(path)
