"""Histogram gradient-boosting wrapper for the WP2.5 controlled comparison.

Mirrors ``touchline.modeling.logistic`` in shape so the two candidate families are scored by the
same protocol code. Four locked properties, all pre-registered in ADR 0011 / the WP2.5 contract:

- **The declared search space** (D14) is exactly twelve points — ``learning_rate`` in
  ``{0.03, 0.06, 0.1}`` times ``max_leaf_nodes`` in ``{7, 15}`` times ``min_samples_leaf`` in
  ``{20, 60}``. It is enumerated as a tuple, not generated from ranges, so a reviewer can count it.
- **Everything else is fixed, not searched** (D15): ``max_iter=200``, ``l2_regularization=1.0``,
  ``max_bins=255``, ``early_stopping=False``. Early stopping is deliberately off: it would need an
  inner validation split inside a fold structure WP2.3 locked and proved.
- **Selection follows D16**: unweighted arithmetic mean of the five fold-level log losses, ties
  broken by mean Brier, then by the hyperparameters in a fixed order. The key is total, so repeat
  runs and row-order changes cannot move the choice.
- **Determinism is the caller's job to pin** (D20): histogram boosting sums gradients in a
  thread-dependent order, so the training entry point wraps every fit in
  ``threadpoolctl.threadpool_limits(1)``. This module fixes ``random_state`` and nothing else.

Nothing here reads a label outside a training fold.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from sklearn.ensemble import HistGradientBoostingClassifier  # type: ignore[import-untyped]

from touchline.modeling.metrics import brier_score, log_loss

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int_]

#: Pre-registered seed (D12). Fixed before any model output is viewed.
EVALUATION_SEED = 0

#: Pre-registered fixed hyperparameters (D15): held constant so the declared grid's three axes are
#: the only moving parts of the search.
MAX_ITER = 200
L2_REGULARIZATION = 1.0
MAX_BINS = 255
EARLY_STOPPING = False


@dataclass(frozen=True)
class BoostingParams:
    """One point of the declared search space (D14)."""

    learning_rate: float
    max_leaf_nodes: int
    min_samples_leaf: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "learning_rate": self.learning_rate,
            "max_leaf_nodes": self.max_leaf_nodes,
            "min_samples_leaf": self.min_samples_leaf,
        }

    def label(self) -> str:
        """Compact record label, e.g. ``lr=0.03;leaves=7;minleaf=20``."""
        return (
            f"lr={self.learning_rate};leaves={self.max_leaf_nodes};minleaf={self.min_samples_leaf}"
        )


#: The declared search space (D14): exactly twelve points, written out rather than generated.
#: Ordered learning_rate-major so the D16 tie-break reads in the same order it is enumerated.
GBM_GRID: tuple[BoostingParams, ...] = (
    BoostingParams(learning_rate=0.03, max_leaf_nodes=7, min_samples_leaf=20),
    BoostingParams(learning_rate=0.03, max_leaf_nodes=7, min_samples_leaf=60),
    BoostingParams(learning_rate=0.03, max_leaf_nodes=15, min_samples_leaf=20),
    BoostingParams(learning_rate=0.03, max_leaf_nodes=15, min_samples_leaf=60),
    BoostingParams(learning_rate=0.06, max_leaf_nodes=7, min_samples_leaf=20),
    BoostingParams(learning_rate=0.06, max_leaf_nodes=7, min_samples_leaf=60),
    BoostingParams(learning_rate=0.06, max_leaf_nodes=15, min_samples_leaf=20),
    BoostingParams(learning_rate=0.06, max_leaf_nodes=15, min_samples_leaf=60),
    BoostingParams(learning_rate=0.1, max_leaf_nodes=7, min_samples_leaf=20),
    BoostingParams(learning_rate=0.1, max_leaf_nodes=7, min_samples_leaf=60),
    BoostingParams(learning_rate=0.1, max_leaf_nodes=15, min_samples_leaf=20),
    BoostingParams(learning_rate=0.1, max_leaf_nodes=15, min_samples_leaf=60),
)

#: One per-fold split: (X_train, X_val, y_train, y_val), matching ``logistic.FoldSpec`` so the two
#: families consume the identical encoded matrices.
FoldSpec = tuple[FloatArray, FloatArray, IntArray, IntArray]
"""(X_train, X_val, y_train, y_val)."""


@dataclass(frozen=True)
class BoostingModel:
    """A fitted booster and the grid point that produced it."""

    estimator: HistGradientBoostingClassifier
    params: BoostingParams

    def predict_proba(self, X: FloatArray) -> FloatArray:
        """Return P(goal) for each row (second column of ``predict_proba``)."""
        return np.asarray(self.estimator.predict_proba(X), dtype=np.float64)[:, 1]


def fit_boosting(
    X_train: FloatArray,
    y_train: IntArray,
    params: BoostingParams,
    *,
    random_state: int = EVALUATION_SEED,
) -> BoostingModel:
    """Fit one histogram gradient-boosting model at a declared grid point.

    Every non-grid hyperparameter is the pre-registered D15 constant. ``early_stopping`` is off, so
    the fit always runs exactly ``MAX_ITER`` boosting iterations and never consumes a validation
    split of its own.
    """
    estimator = HistGradientBoostingClassifier(
        learning_rate=params.learning_rate,
        max_leaf_nodes=params.max_leaf_nodes,
        min_samples_leaf=params.min_samples_leaf,
        max_iter=MAX_ITER,
        l2_regularization=L2_REGULARIZATION,
        max_bins=MAX_BINS,
        early_stopping=EARLY_STOPPING,
        random_state=random_state,
    )
    estimator.fit(np.asarray(X_train, dtype=np.float64), np.asarray(y_train).ravel())
    return BoostingModel(estimator=estimator, params=params)


def _evaluate_on_spec(model: BoostingModel, spec: FoldSpec) -> tuple[float, float]:
    _X_train, X_val, _y_train, y_val = spec
    predictions = model.predict_proba(X_val)
    return log_loss(y_val, predictions), brier_score(y_val, predictions)


def _selection_key(entry: dict[str, float]) -> tuple[float, float, float, float, float]:
    """D16's total ordering: mean log loss, then mean Brier, then the grid axes in fixed order."""
    return (
        entry["mean_log_loss"],
        entry["mean_brier"],
        entry["learning_rate"],
        entry["max_leaf_nodes"],
        entry["min_samples_leaf"],
    )


def select_hyperparameters(
    fold_specs: Sequence[FoldSpec],
    grid: Sequence[BoostingParams] = GBM_GRID,
    *,
    random_state: int = EVALUATION_SEED,
) -> tuple[BoostingParams, list[dict[str, float]]]:
    """Select one grid point by unweighted mean fold log loss (D16).

    Returns ``(best_params, scored)`` where ``scored`` carries, per grid point, the three
    hyperparameters plus ``mean_log_loss`` and ``mean_brier`` (unweighted means of the fold-level
    values). The ordering key is total, so the selection is deterministic: no tie can be resolved
    by iteration order.
    """
    if not grid:
        raise ValueError("the declared search space is empty")
    scored: list[dict[str, float]] = []
    for params in grid:
        fold_log_losses: list[float] = []
        fold_briers: list[float] = []
        for spec in fold_specs:
            X_train, _X_val, y_train, _y_val = spec
            model = fit_boosting(X_train, y_train, params, random_state=random_state)
            fold_log_loss, fold_brier = _evaluate_on_spec(model, spec)
            fold_log_losses.append(fold_log_loss)
            fold_briers.append(fold_brier)
        scored.append(
            {
                "learning_rate": float(params.learning_rate),
                "max_leaf_nodes": float(params.max_leaf_nodes),
                "min_samples_leaf": float(params.min_samples_leaf),
                "mean_log_loss": float(np.mean(fold_log_losses)),
                "mean_brier": float(np.mean(fold_briers)),
            }
        )
    best = min(scored, key=_selection_key)
    best_params = BoostingParams(
        learning_rate=float(best["learning_rate"]),
        max_leaf_nodes=int(best["max_leaf_nodes"]),
        min_samples_leaf=int(best["min_samples_leaf"]),
    )
    return best_params, scored
