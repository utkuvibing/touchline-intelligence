"""Regularized logistic regression wrapper for the WP2.4 evaluation protocol.

L2-regularized, liblinear-free (``lbfgs``), deterministic under a fixed seed, and converged or
dead. Three locked properties:

- **The pre-registered C grid** (D10) is ``{0.01, 0.1, 1.0, 10.0}``; ``select_regularization``
  picks C by the **unweighted arithmetic mean of the five fold-level log losses**, ties broken by
  lower mean Brier, then by **smallest C (strongest regularization)** — PLAN §4.1's "ties go to
  the simpler model".
- **Non-convergence fails loudly** (``NonConvergenceError``) rather than quietly returning a model
  that stopped at ``max_iter``; the cap is ``MAX_ITER``.
- **The solver API is the still-supported L2 form**: ``penalty`` stays at its default and the L2
  choice is expressed as ``l1_ratio=0``, so this wrapper does not trip the sklearn 1.8→1.10
  ``penalty`` deprecation. ``fit_logistic`` asserts convergence via ``n_iter_``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]

from touchline.modeling.metrics import brier_score, log_loss

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int_]

#: Pre-registered L2 regularization grid (D10): fixed before any model output is viewed.
L2_C_GRID: tuple[float, ...] = (0.01, 0.1, 1.0, 10.0)

#: Pre-registered upper cap on lbfgs iterations. Convergence is asserted separately; reaching the
#: cap must raise, not silently accept a model that stopped early.
MAX_ITER = 100_000

#: Pre-registered solver tolerance and random seed. lbfgs on a binary problem is deterministic, so
#: the seed is recorded for strict reproducibility rather than because randomness is involved.
SOLVER_TOL = 1e-4
EVALUATION_SEED = 0


class NonConvergenceError(RuntimeError):
    """lbfgs stopped at the iteration cap; the returned coefficients would be stale."""


#: One per-fold split: (X_train, X_val, y_train, y_val). The scaler has already been applied with
#: validation rows held out at fit time (preprocessing contract).
FoldSpec = tuple[FloatArray, FloatArray, IntArray, IntArray]
"""(X_train, X_val, y_train, y_val)."""


@dataclass(frozen=True)
class LogisticModel:
    """A fitted logistic model and its selected C, with a converged-or-raise guarantee."""

    estimator: LogisticRegression
    c_value: float

    def predict_proba(self, X: FloatArray) -> FloatArray:
        """Return P(goal) for each row (second column of ``predict_proba``)."""
        return np.asarray(self.estimator.predict_proba(X), dtype=np.float64)[:, 1]


def fit_logistic(
    X_train: FloatArray,
    y_train: IntArray,
    c_value: float,
    *,
    max_iter: int = MAX_ITER,
    tol: float = SOLVER_TOL,
    random_state: int = EVALUATION_SEED,
) -> LogisticModel:
    """Fit L2 logistic regression and assert convergence.

    ``penalty`` is left at its default; the L2 choice is carried by ``l1_ratio=0`` to stay clear
    of the sklearn ``penalty`` deprecation. Convergence is asserted from ``n_iter_[0] < max_iter``.
    """
    estimator = LogisticRegression(
        solver="lbfgs",
        l1_ratio=0.0,
        C=c_value,
        max_iter=max_iter,
        tol=tol,
        random_state=random_state,
    )
    estimator.fit(np.asarray(X_train, dtype=np.float64), np.asarray(y_train).ravel())
    if int(estimator.n_iter_[0]) >= max_iter:
        raise NonConvergenceError(
            f"lbfgs stopped at the {max_iter}-iteration cap for C={c_value}; coefficients are stale"
        )
    return LogisticModel(estimator=estimator, c_value=c_value)


def _evaluate_on_spec(model: LogisticModel, spec: FoldSpec) -> tuple[float, float]:
    _X_train, X_val, _y_train, y_val = spec
    predictions = model.predict_proba(X_val)
    return log_loss(y_val, predictions), brier_score(y_val, predictions)


def select_regularization(
    fold_specs: Sequence[FoldSpec],
    grid: Sequence[float] = L2_C_GRID,
    *,
    random_state: int = EVALUATION_SEED,
) -> tuple[float, list[dict[str, float]]]:
    """Select C by unweighted mean fold log loss; ties -> mean Brier -> smallest C.

    Returns ``(best_c, scored)`` where ``scored`` carries, per grid value, ``mean_log_loss`` and
    ``mean_brier`` (unweighted means of the five fold-level values) and ``best_c`` obeys D10. The
    per-fold fits are deterministic under the fixed seed.
    """
    scored: list[dict[str, float]] = []
    for c_value in grid:
        fold_log_losses: list[float] = []
        fold_briers: list[float] = []
        for spec in fold_specs:
            X_train, _X_val, y_train, _y_val = spec
            model = fit_logistic(X_train, y_train, c_value, random_state=random_state)
            fold_log_losses.append(_evaluate_on_spec(model, spec)[0])
            fold_briers.append(_evaluate_on_spec(model, spec)[1])
        scored.append(
            {
                "C": float(c_value),
                "mean_log_loss": float(np.mean(fold_log_losses)),
                "mean_brier": float(np.mean(fold_briers)),
            }
        )
    best = min(scored, key=lambda entry: (entry["mean_log_loss"], entry["mean_brier"], entry["C"]))
    return float(best["C"]), scored
