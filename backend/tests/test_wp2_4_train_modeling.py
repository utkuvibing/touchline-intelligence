"""Unit contracts for the WP2.4 training internals that the mutation suite protects.

Two exact discriminator tests — both are written so a leak *changes a number*, not just a code
path, and each is the seat for one registered mutation:

- the constant baseline must be trained on **training rows only**: on a fold whose training goal
  rate differs from the combined (train+validation) rate, the constant's per-fold log loss must
  equal the value computed from the training-fold rate alone;
- the fold scaler must be fitted on **training rows only**: when a held-out fold contains an
  extreme distance, its scaled value must use the training-fold mean/SD exactly, and must differ
  from what a leaked co-fit would produce.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import cast

import numpy as np

from touchline.modeling.artifact import ArtifactBundle, infer
from touchline.modeling.baselines import ConstantBaseline
from touchline.modeling.logistic import L2_C_GRID
from touchline.modeling.metrics import log_loss
from touchline.modeling.preprocessing import (
    CONTINUOUS_FIELDS,
    PRESENCE_SOURCE_FIELDS,
    ShotRow,
    encode_rows,
    fit_scaler,
)
from touchline.modeling.protocol import build_folds, evaluate_constant
from touchline.modeling.train import (
    RunConfig,
    build_vocabulary,
    run_protocol,
)

TRAIN_Y: dict[int, list[int]] = {
    0: [1, 1, 1, 0, 0, 0],
    1: [1, 1, 1, 1, 0, 0],
    2: [1, 0, 0, 0, 0, 0],  # 1/6 training rate; validation [1,1] makes the combined rate 3/8.
    3: [1, 1, 0, 0, 0, 0],
    4: [1, 1, 1, 1, 1, 0],
}
VAL_Y: dict[int, list[int]] = {0: [1, 0], 1: [1, 0], 2: [1, 1], 3: [1, 0], 4: [1, 0]}


def _synthetic_rows(n_folds: int = 5, distance: float = 20.0) -> list[ShotRow]:
    rows: list[ShotRow] = []
    for fold in range(n_folds):
        for j, y in enumerate(TRAIN_Y[fold]):
            rows.append(_shot(y, fold, distance + 0.5 * j, angle=0.1 + 0.05 * j))
        for j, y in enumerate(VAL_Y[fold]):
            rows.append(_shot(y, fold, distance + 0.5 * j, angle=0.1 + 0.05 * j))
    return rows


def _shot(y: int, fold: int, distance: float, angle: float = 0.3) -> ShotRow:
    return ShotRow(
        shot_id=f"s{fold}-{y}",
        match_id=100 + fold,
        fold=fold,
        competition_id=43,
        season_id=3,
        y=y,
        distance_to_goal=distance,
        visible_goal_angle=angle,
        body_part_name="Right Foot",
        technique_name="Normal",
        play_pattern_name="Regular Play",
        first_time=None,
        under_pressure=None,
    )


def _make_config() -> RunConfig:
    return RunConfig(
        experiment_id="unit-test",
        out_dir="experiments/shot_quality/unit-test",
        artifacts_dir="artifacts/models/unit-test",
        code_commit="unit-test-code",
        reproduction_commit="unit-test-code",
        data_source_commit="b0bc9f22dd77c206ddedc1d742893b3bbe64baec",
        input_config_path="experiments/run-configs/unit-test.json",
        input_config_sha256="0" * 64,
        uv_lock_sha256="0" * 64,
        runtime_fingerprint={},
        require_clean_provenance=False,
        db_url_env="TOUCHLINE_DB_URL",
        assignments_sha256="0" * 64,
        cohort_sql_sha256="0" * 64,
        c_grid=L2_C_GRID,
        random_seed=0,
        n_folds=5,
        expected_shots=100,
        expected_matches=5,
        expected_fold_sizes={0: 20, 1: 20, 2: 20, 3: 20, 4: 20},
        bin_count=5,
        results_csv="experiments/results.csv",
    )


def _d5_rows(*, informative: bool, seed: int) -> list[ShotRow]:
    """Balanced 5x20 rows; two presence indicators either informative or pure noise.

    ``informative=True`` aligns ``first_time`` (90%) and ``under_pressure`` (70%) with the goal
    so the full model should clearly beat the minus model (D5 include). ``informative=False`` makes
    both indicators independent noise so D5 should exclude.
    """
    rng = np.random.default_rng(seed)
    rows: list[ShotRow] = []
    for fold in range(5):
        for i in range(20):
            y = 1 if i < 10 else 0
            distance = 20.0 + float(rng.normal(0, 1))
            angle = 0.3 + 0.02 * float(rng.normal(0, 1))
            ft: bool | None
            up: bool | None
            if informative:
                ft = bool((rng.random() < 0.9) == (y == 1))
                up = bool((rng.random() < 0.7) == (y == 1))
            else:
                ft = bool(rng.random() < 0.2)
                up = bool(rng.random() < 0.3)
            rows.append(
                ShotRow(
                    shot_id=f"d{seed}-{fold}-{i}",
                    match_id=200 + fold,
                    fold=fold,
                    competition_id=43,
                    season_id=3,
                    y=y,
                    distance_to_goal=distance,
                    visible_goal_angle=angle,
                    body_part_name="Right Foot",
                    technique_name="Normal",
                    play_pattern_name="Regular Play",
                    first_time=ft,
                    under_pressure=up,
                )
            )
    return rows


def _assert_shipped_and_bundle(
    metrics: dict[str, object],
    bundle: object,
    *,
    include: bool,
    rows: list[ShotRow],
) -> None:
    assert isinstance(bundle, ArtifactBundle)
    assert metrics["d5_include"] is include
    expected_ship = "full_logistic" if include else "full_minus_presence"
    assert metrics["shipped_candidate"] == expected_ship
    candidates: Mapping[str, object] = cast(Mapping[str, object], metrics["candidates"])
    expected_candidate = cast(Mapping[str, object], candidates[expected_ship])
    assert metrics["shipped_best_c"] == cast(float, expected_candidate["best_c"])
    shipped_columns = cast(Sequence[str], metrics["shipped_feature_columns"])
    has_presence = any("_presence" in col for col in shipped_columns)
    assert has_presence is include
    assert list(bundle.selected_columns) == list(shipped_columns)
    assert bundle.shipped_candidate == expected_ship
    expected_indices = tuple(bundle.all_columns.index(col) for col in shipped_columns)
    assert bundle.selected_indices == expected_indices
    # Shipped coefficients never carry the rejected candidate's presence columns.
    coefficient_entries = cast(Sequence[Mapping[str, object]], metrics["coefficients"])
    coefficient_features = [str(entry["feature"]) for entry in coefficient_entries]
    assert any("_presence" in f for f in coefficient_features) is include
    # Bundle inference from raw rows equals the persisted preprocessing + fitted estimator.
    query = rows[:10]
    via_bundle = infer(bundle, query)
    full_encoded, _ = encode_rows(query, bundle.vocabulary, bundle.scaler)
    subset = full_encoded[:, list(bundle.selected_indices)]
    expected = bundle.estimator.predict_proba(subset)[:, 1]
    assert np.array_equal(via_bundle, expected)
    assert bundle.estimator.n_features_in_ == len(bundle.selected_columns)


def test_d5_include_ships_full_logistic_with_presence() -> None:
    rows = _d5_rows(informative=True, seed=11)
    metrics, bundle = run_protocol(rows, _make_config())
    assert metrics["d5_include"] is True
    _assert_shipped_and_bundle(metrics, bundle, include=True, rows=rows)


def test_d5_exclude_ships_full_minus_presence_without_presence() -> None:
    rows = _d5_rows(informative=False, seed=22)
    metrics, bundle = run_protocol(rows, _make_config())
    assert metrics["d5_include"] is False
    _assert_shipped_and_bundle(metrics, bundle, include=False, rows=rows)


def test_candidate_column_subsets_are_resolved_by_name_not_by_position() -> None:
    """The geometry and minus-presence subsets must be defined by their contracted column names.

    The protocol used to address these subsets with hard-coded positions (``[0, 1]``/``[2, 3]``).
    That is right only as long as ``Vocabulary.column_names()`` never changes order; if it did, the
    'geometry-only' candidate would silently become something else while every record still claimed
    the locked feature set. The shipped columns must equal the full column list minus exactly the
    presence indicators, by name.
    """
    rows = _d5_rows(informative=False, seed=22)
    metrics, bundle = run_protocol(rows, _make_config())
    all_columns = list(bundle.all_columns)
    presence_names = [f"{field}_presence" for field in PRESENCE_SOURCE_FIELDS]

    assert all_columns[: len(CONTINUOUS_FIELDS)] == list(CONTINUOUS_FIELDS)
    assert set(presence_names) <= set(all_columns)
    shipped_columns = cast(Sequence[str], metrics["shipped_feature_columns"])
    assert list(shipped_columns) == [c for c in all_columns if c not in presence_names]
    assert list(bundle.selected_columns) == list(shipped_columns)
    assert [all_columns[i] for i in bundle.selected_indices] == list(shipped_columns)


def test_constant_baseline_trains_on_the_training_fold_only() -> None:
    rows = _synthetic_rows()
    metrics = evaluate_constant(rows, 5)
    per_fold = metrics["per_fold"]
    assert isinstance(per_fold, list)
    assert isinstance(per_fold[0], dict)
    any_distinct = False
    for fold in range(5):
        train = [r for r in rows if r.fold != fold]
        val = [r for r in rows if r.fold == fold]
        correct = ConstantBaseline.fit([r.y for r in train])
        expected_loss = log_loss([r.y for r in val], correct.predictions(len(val)))
        assert math.isclose(per_fold[fold]["log_loss"], expected_loss, abs_tol=1e-12), fold
        leaked = ConstantBaseline.fit([r.y for r in train] + [r.y for r in val])
        if not math.isclose(correct.rate, leaked.rate, rel_tol=1e-9):
            any_distinct = True
    assert any_distinct, "the synthetic folds must discriminate a leaked constant"


def test_fold_scaler_is_fitted_on_training_rows_only() -> None:
    rows = _synthetic_rows()
    # Fold 0's validation holds an extreme distance; its scaled value must use fold-0 train stats.
    extreme = rows[-1]
    rows[-1] = ShotRow(
        **{
            **vars(extreme),
            "distance_to_goal": 999.0,
        }
    )
    vocabulary = build_vocabulary(rows)
    folds = build_folds(rows, vocabulary, 5)
    fold0_train = [r for r in rows if r.fold != 0]
    fold0_val = [r for r in rows if r.fold == 0]
    scaler = fit_scaler(fold0_train)
    expected_matrix, _ = encode_rows(fold0_val, vocabulary, scaler)
    assert math.isclose(folds[0].X_val[-1, 0], expected_matrix[-1, 0], abs_tol=1e-12)
    # The extreme value actually changes the scale: a leaked co-fit would give a different number.
    leaked = fit_scaler(fold0_train + fold0_val)
    leak_matrix, _ = encode_rows(fold0_val, vocabulary, leaked)
    assert not math.isclose(folds[0].X_val[-1, 0], leak_matrix[-1, 0], abs_tol=1e-9)
