"""Unit contracts for the WP2.4 baselines and logistic wrapper. Synthetic data, no database.

- the constant baseline is the training-fold goal rate and nothing else (never a cohort-level rate);
- L2 ``lbfgs`` fits converge or raise ``NonConvergenceError``; the wrapper uses the still-supported
  solver API (``l1_ratio=0``, not the deprecated ``penalty='l2'``);
- C selection is the pre-registered unweighted-mean-of-fold-log-loss rule with ties to Brier then
  to the smallest C (D10), reproduced as a pure selection over returned scores, and is
  deterministic; an exact-tie degeneracy selects the strongest regularization (0.01);
- ``evaluate_probability_scores`` separates per-fold tables, the unweighted mean of fold log
  losses, a ddof=0 cross-fold standard deviation, and pooled out-of-fold metrics, and raises on a
  single-class fold.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from touchline.modeling.baselines import ConstantBaseline, EmptyTrainingError
from touchline.modeling.logistic import (
    L2_C_GRID,
    NonConvergenceError,
    fit_logistic,
    select_regularization,
)
from touchline.modeling.metrics import (
    SingleClassFoldError,
    brier_score,
    evaluate_probability_scores,
    log_loss,
)

SpecTuple = tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]


def _well_separated_specs(fold_count: int = 5) -> list[SpecTuple]:
    specs: list[SpecTuple] = []
    rng = np.random.default_rng(7)
    for _ in range(fold_count):
        pos = np.column_stack([rng.normal(2.0, 0.5, 30), rng.normal(-1.0, 0.5, 30)])
        neg = np.column_stack([rng.normal(-2.0, 0.5, 30), rng.normal(1.0, 0.5, 30)])
        X = np.concatenate([pos, neg])
        y = np.concatenate([np.ones(30), np.zeros(30)]).astype(np.int_)
        val = rng.permutation(X.shape[0])[:12]
        mask = np.ones(X.shape[0], dtype=bool)
        mask[val] = False
        specs.append((X[mask], X[val], y[mask], y[val]))
    return specs


def test_constant_baseline_is_the_training_fold_rate() -> None:
    model = ConstantBaseline.fit([0, 0, 1, 1, 1])
    assert model.rate == 0.6
    preds = model.predictions(4)
    assert list(preds) == [0.6, 0.6, 0.6, 0.6]
    # fit() is a pure function of the training vector it is given and nothing else.
    assert ConstantBaseline.fit([0, 1]).rate == 0.5
    assert ConstantBaseline.fit([0, 0, 1]).rate == 1 / 3


def test_a_fitted_constant_baseline_rate_cannot_be_reassigned() -> None:
    """The class documents itself as immutable; that must be behaviour, not a comment.

    Which rows produced the rate is the entire contract of this baseline, so a rate that could be
    re-pointed after the fit would make the fold provenance unverifiable.
    """
    model = ConstantBaseline.fit([0, 0, 1, 1, 1])
    with pytest.raises(AttributeError):
        model.rate = 0.9
    with pytest.raises(AttributeError):
        del model.rate
    assert model.rate == 0.6


def test_constant_baseline_equality_and_empty_guard() -> None:
    assert ConstantBaseline.fit([0, 1]) == ConstantBaseline.fit([0, 1])
    with pytest.raises(EmptyTrainingError):
        ConstantBaseline.fit([])


def test_logistic_fit_converges_and_separates() -> None:
    X = np.array([[0.0], [1.0], [2.0], [3.0], [4.0], [5.0]])
    y = np.array([0, 0, 0, 1, 1, 1])
    model = fit_logistic(X, y, c_value=1.0)
    p = model.predict_proba(np.array([[0.0], [5.0]]))
    assert p[0] < 0.5 < p[1]
    assert 0.0 <= p[0] <= 1.0 and 0.0 <= p[1] <= 1.0


def test_logistic_non_convergence_fails_loudly() -> None:
    import warnings

    from sklearn.exceptions import ConvergenceWarning  # type: ignore[import-untyped]

    X = np.array([[0.0], [1.0], [2.0], [3.0], [4.0], [5.0]])
    y = np.array([0, 0, 0, 1, 1, 1])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        with pytest.raises(NonConvergenceError):
            fit_logistic(X, y, c_value=10.0, max_iter=1)


def test_c_selection_follows_mean_log_loss_and_is_deterministic() -> None:
    specs = _well_separated_specs()
    best_a, scored_a = select_regularization(specs)
    best_b, scored_b = select_regularization(specs)
    assert best_a == best_b
    assert scored_a == scored_b
    assert best_a in L2_C_GRID

    def selection_key(entry: dict[str, float]) -> tuple[float, float, float]:
        return (entry["mean_log_loss"], entry["mean_brier"], entry["C"])

    assert best_a == min(scored_a, key=selection_key)["C"]


def test_c_selection_ties_resolve_to_smallest_c() -> None:
    # All-zero features -> every C fits the intercept-only model -> identical metrics -> tie.
    train_x = np.zeros((20, 2))
    train_y = np.array([1] * 10 + [0] * 10)
    val_x = np.zeros((6, 2))
    val_y = np.array([1, 1, 1, 0, 0, 0])
    specs = [(train_x, val_x, train_y, val_y)] * 5
    best_c, scored = select_regularization(specs)
    assert best_c == min(entry["C"] for entry in scored)


def test_evaluate_probability_scores_separates_aggregates() -> None:
    fold0 = ([0, 1, 0], [0.2, 0.8, 0.3])
    fold1 = ([1, 0, 1], [0.6, 0.4, 0.7])
    result = evaluate_probability_scores([fold0, fold1])
    per_fold = result["per_fold"]
    assert isinstance(per_fold, list)
    assert len(per_fold) == 2
    mean_log_loss = result["mean_log_loss"]
    assert isinstance(mean_log_loss, float)
    expected_mean = (log_loss(*fold0) + log_loss(*fold1)) / 2.0
    assert math.isclose(mean_log_loss, expected_mean, abs_tol=1e-12)
    sd_log_loss = result["sd_log_loss_ddof0"]
    assert isinstance(sd_log_loss, float)
    fold_logs = [log_loss(*fold0), log_loss(*fold1)]
    expected_sd = float(np.std(fold_logs, ddof=0))
    assert math.isclose(sd_log_loss, expected_sd, abs_tol=1e-12)
    pooled = result["pooled_oof"]
    assert isinstance(pooled, dict)
    assert pooled["n"] == 6 and pooled["positive_count"] == 3 and pooled["prevalence"] == 0.5
    reliability = result["reliability"]
    assert isinstance(reliability, list)
    assert len(reliability) == 5
    # Per-fold Brier path also reported.
    assert isinstance(per_fold[0], dict)
    assert math.isclose(per_fold[0]["brier"], brier_score(*fold0), abs_tol=1e-12)


def test_evaluate_probability_scores_fails_loudly_on_single_class_fold() -> None:
    with pytest.raises(SingleClassFoldError):
        evaluate_probability_scores([([1, 1, 1], [0.5, 0.6, 0.7]), ([1, 0, 1], [0.6, 0.4, 0.7])])
