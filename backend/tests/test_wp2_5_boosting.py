"""Unit contracts for the WP2.5 boosting wrapper and its pre-registered search space.

Four things are protected here, all of them pre-registration properties rather than accuracy
claims:

- **the declared grid is exactly the twelve D14 points** — written out, not generated, so a
  reviewer can count it and a silent widening fails;
- **selection is deterministic and its ordering is total** (D16): repeat calls agree, and a
  perfect tie resolves to the pre-registered smallest point rather than to iteration order;
- **the fixed hyperparameters are the D15 constants**, in particular ``early_stopping=False`` —
  early stopping would consume an inner validation split inside a locked fold;
- **a single-class validation fold fails loudly** rather than scoring a degenerate fold.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pytest

from touchline.modeling.boosting import (
    EARLY_STOPPING,
    GBM_GRID,
    L2_REGULARIZATION,
    MAX_BINS,
    MAX_ITER,
    BoostingParams,
    FoldSpec,
    fit_boosting,
    select_hyperparameters,
)
from touchline.modeling.metrics import SingleClassFoldError
from touchline.modeling.protocol import FoldData, score_folds

FloatArray = npt.NDArray[np.float64]

#: A deliberately small subset for the fast tests. The full twelve-point grid is exercised only by
#: the shape test, which does not fit anything.
SMALL_GRID = (
    BoostingParams(learning_rate=0.06, max_leaf_nodes=7, min_samples_leaf=20),
    BoostingParams(learning_rate=0.1, max_leaf_nodes=15, min_samples_leaf=60),
)


def _separable_specs(n_folds: int = 3, per_fold: int = 60, seed: int = 3) -> list[FoldSpec]:
    """Folds whose single feature separates the classes, with both classes in every fold."""
    rng = np.random.default_rng(seed)
    specs: list[FoldSpec] = []
    for _ in range(n_folds):
        y_train = np.asarray([1] * (per_fold // 2) + [0] * (per_fold // 2), dtype=np.int_)
        y_val = np.asarray([1] * 10 + [0] * 10, dtype=np.int_)
        X_train = (y_train.astype(np.float64) + 0.4 * rng.normal(size=y_train.size)).reshape(-1, 1)
        X_val = (y_val.astype(np.float64) + 0.4 * rng.normal(size=y_val.size)).reshape(-1, 1)
        specs.append((X_train, X_val, y_train, y_val))
    return specs


def _constant_specs(n_folds: int = 3) -> list[FoldSpec]:
    """Zero-variance features: every grid point must score identically, forcing a pure tie."""
    specs: list[FoldSpec] = []
    for _ in range(n_folds):
        y_train = np.asarray([1] * 20 + [0] * 60, dtype=np.int_)
        y_val = np.asarray([1] * 5 + [0] * 15, dtype=np.int_)
        X_train = np.zeros((y_train.size, 2), dtype=np.float64)
        X_val = np.zeros((y_val.size, 2), dtype=np.float64)
        specs.append((X_train, X_val, y_train, y_val))
    return specs


def test_declared_grid_is_exactly_the_twelve_pre_registered_points() -> None:
    """D14 is a pre-registration, not a default: its size and membership are the contract."""
    assert len(GBM_GRID) == 12
    assert len(set(GBM_GRID)) == 12
    expected = {
        BoostingParams(learning_rate=lr, max_leaf_nodes=leaves, min_samples_leaf=min_leaf)
        for lr in (0.03, 0.06, 0.1)
        for leaves in (7, 15)
        for min_leaf in (20, 60)
    }
    assert set(GBM_GRID) == expected
    assert sorted({p.learning_rate for p in GBM_GRID}) == [0.03, 0.06, 0.1]
    assert sorted({p.max_leaf_nodes for p in GBM_GRID}) == [7, 15]
    assert sorted({p.min_samples_leaf for p in GBM_GRID}) == [20, 60]


def test_fixed_hyperparameters_are_the_d15_constants() -> None:
    """Especially ``early_stopping=False``: an inner split would subdivide a locked fold."""
    assert MAX_ITER == 200
    assert L2_REGULARIZATION == 1.0
    assert MAX_BINS == 255
    assert EARLY_STOPPING is False

    specs = _separable_specs(n_folds=1)
    X_train, _X_val, y_train, _y_val = specs[0]
    model = fit_boosting(X_train, y_train, SMALL_GRID[0])
    params = model.estimator.get_params()
    assert params["early_stopping"] is False
    assert params["max_iter"] == MAX_ITER
    assert params["l2_regularization"] == L2_REGULARIZATION
    assert params["max_bins"] == MAX_BINS
    assert params["random_state"] == 0
    # The grid point actually reached the estimator, rather than a library default.
    assert params["learning_rate"] == SMALL_GRID[0].learning_rate
    assert params["max_leaf_nodes"] == SMALL_GRID[0].max_leaf_nodes
    assert params["min_samples_leaf"] == SMALL_GRID[0].min_samples_leaf


def test_fitted_model_returns_probabilities_and_separates() -> None:
    specs = _separable_specs(n_folds=1)
    X_train, X_val, y_train, y_val = specs[0]
    model = fit_boosting(X_train, y_train, SMALL_GRID[0])
    p = model.predict_proba(X_val)
    assert p.shape == (y_val.size,)
    assert np.all(p >= 0.0) and np.all(p <= 1.0)
    assert float(p[y_val == 1].mean()) > float(p[y_val == 0].mean())


def test_selection_is_deterministic_across_repeat_calls() -> None:
    specs = _separable_specs()
    best_a, scored_a = select_hyperparameters(specs, SMALL_GRID)
    best_b, scored_b = select_hyperparameters(specs, SMALL_GRID)
    assert best_a == best_b
    assert scored_a == scored_b
    assert best_a in SMALL_GRID


def test_selection_follows_mean_log_loss_and_the_total_d16_key() -> None:
    specs = _separable_specs()
    best, scored = select_hyperparameters(specs, SMALL_GRID)
    assert len(scored) == len(SMALL_GRID)

    def key(entry: dict[str, float]) -> tuple[float, ...]:
        return (
            entry["mean_log_loss"],
            entry["mean_brier"],
            entry["learning_rate"],
            entry["max_leaf_nodes"],
            entry["min_samples_leaf"],
        )

    winner = min(scored, key=key)
    assert best.learning_rate == winner["learning_rate"]
    assert best.max_leaf_nodes == int(winner["max_leaf_nodes"])
    assert best.min_samples_leaf == int(winner["min_samples_leaf"])


def test_a_perfect_tie_resolves_to_the_pre_registered_smallest_point() -> None:
    """Zero-variance features make every point score identically; order must not decide."""
    specs = _constant_specs()
    # Feed the grid in reverse so a tie resolved by iteration order would pick the other end.
    best, scored = select_hyperparameters(specs, tuple(reversed(GBM_GRID)))
    losses = {round(entry["mean_log_loss"], 12) for entry in scored}
    assert len(losses) == 1, "the tie construction failed; the points did not score identically"
    assert best == BoostingParams(learning_rate=0.03, max_leaf_nodes=7, min_samples_leaf=20)


def test_an_empty_search_space_fails_loudly() -> None:
    with pytest.raises(ValueError, match="empty"):
        select_hyperparameters(_separable_specs(), ())


def test_a_single_class_validation_fold_fails_loudly() -> None:
    """A degenerate fold is never scored quietly; the protocol raises (inherited WP2.4 contract)."""
    X = np.linspace(0.0, 1.0, 40).reshape(-1, 1)
    y_train = np.asarray([1] * 20 + [0] * 20, dtype=np.int_)
    folds = [
        FoldData(
            X_train=X,
            X_val=X[:10],
            y_train=y_train,
            y_val=np.zeros(10, dtype=np.int_),
            column_names=["f"],
        )
    ]

    def predict(fold: FoldData) -> FloatArray:
        model = fit_boosting(fold.X_train, fold.y_train, SMALL_GRID[0])
        return model.predict_proba(fold.X_val)

    with pytest.raises(SingleClassFoldError):
        score_folds(folds, predict)
