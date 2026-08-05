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

from touchline.modeling.baselines import ConstantBaseline
from touchline.modeling.metrics import log_loss
from touchline.modeling.preprocessing import ShotRow, encode_rows, fit_scaler
from touchline.modeling.train import (
    _build_folds,
    _evaluate_constant,
    build_vocabulary,
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


def test_constant_baseline_trains_on_the_training_fold_only() -> None:
    rows = _synthetic_rows()
    metrics = _evaluate_constant(rows, 5)
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
    folds = _build_folds(rows, vocabulary, 5)
    fold0_train = [r for r in rows if r.fold != 0]
    fold0_val = [r for r in rows if r.fold == 0]
    scaler = fit_scaler(fold0_train)
    expected_matrix, _ = encode_rows(fold0_val, vocabulary, scaler)
    assert math.isclose(folds[0].X_val[-1, 0], expected_matrix[-1, 0], abs_tol=1e-12)
    # The extreme value actually changes the scale: a leaked co-fit would give a different number.
    leaked = fit_scaler(fold0_train + fold0_val)
    leak_matrix, _ = encode_rows(fold0_val, vocabulary, leaked)
    assert not math.isclose(folds[0].X_val[-1, 0], leak_matrix[-1, 0], abs_tol=1e-9)
