"""Model-agnostic evaluation protocol shared by every M2 candidate family.

This module holds the parts of the locked WP2.3/WP2.4 protocol that do not depend on *which*
estimator is being scored: how a development fold is encoded, how the constant baseline is
evaluated, how the D11-supported calibration summary is attached, and how the PLAN §4.1 replacement
rule is applied along a chain of candidates.

It was extracted from ``touchline.modeling.train`` so that WP2.5's gradient-boosting entry point can
reuse the identical protocol without importing the WP2.4 logistic runner. The extraction is
behaviour-preserving: every function body moved verbatim, and ``train`` re-exports nothing it did
not already own.

Nothing here fits a model, reads a label outside a training fold, or touches the calibration or
holdout splits.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TypedDict, cast

import numpy as np
import numpy.typing as npt

from touchline.modeling.baselines import ConstantBaseline
from touchline.modeling.metrics import (
    EvaluationResult,
    PerFoldMetrics,
    ReliabilityEntry,
    evaluate_probability_scores,
)
from touchline.modeling.preprocessing import (
    ShotRow,
    Vocabulary,
    encode_rows,
    fit_scaler,
)

#: Pre-registered D5/D11 floor: a reliability bin counts toward the calibration comparison only
#: when it holds at least this many pooled out-of-fold predictions.
D11_MIN_SUPPORT = 100

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int_]


@dataclass(frozen=True)
class FoldData:
    """One development fold's encoded matrices. The scaler was fitted on training rows only."""

    X_train: FloatArray
    X_val: FloatArray
    y_train: IntArray
    y_val: IntArray
    column_names: list[str]


class _RuleMetrics(TypedDict):
    """The fields the PLAN §4.1 replacement rule reads, structurally typed for the cast."""

    mean_log_loss: float
    sd_log_loss_ddof0: float
    max_abs_deviation_supported: float


def supported_deviations(
    reliability: Sequence[ReliabilityEntry], min_support: int
) -> tuple[float, int]:
    """Max |mean_prediction - observed_rate| over supported bins, and the supported-bin count."""
    deviations: list[float] = []
    for entry in reliability:
        if entry["count"] < min_support or entry["observed_rate"] is None:
            continue
        mean_prediction = entry["mean_prediction"]
        if mean_prediction is not None:
            deviations.append(abs(mean_prediction - entry["observed_rate"]))
    if not deviations:
        return 0.0, 0
    return float(max(deviations)), len(deviations)


def finalize_metrics(metrics: EvaluationResult) -> dict[str, object]:
    """Attach the D11-supported calibration summary the §4.1 rule reads."""
    max_deviation, supported_bins = supported_deviations(metrics["reliability"], D11_MIN_SUPPORT)
    return {
        **metrics,
        "max_abs_deviation_supported": max_deviation,
        "supported_bins": supported_bins,
    }


def evaluate_constant(rows: Sequence[ShotRow], n_folds: int) -> dict[str, object]:
    """Score the constant baseline out-of-fold; its rate is the training fold's goal rate only."""
    fold_pairs: list[tuple[IntArray, FloatArray]] = []
    for fold in range(n_folds):
        train = [r for r in rows if r.fold != fold]
        val = [r for r in rows if r.fold == fold]
        baseline = ConstantBaseline.fit([r.y for r in train])
        fold_pairs.append(
            (np.asarray([r.y for r in val], dtype=np.int_), baseline.predictions(len(val)))
        )
    return finalize_metrics(evaluate_probability_scores(fold_pairs))


def build_folds(
    rows: Sequence[ShotRow],
    vocabulary: Vocabulary,
    n_folds: int,
) -> list[FoldData]:
    """Per-fold encoded matrices; the scaler is fitted on **training rows only** per fold."""
    selected_folds: list[FoldData] = []
    for fold in range(n_folds):
        train = [r for r in rows if r.fold != fold]
        val = [r for r in rows if r.fold == fold]
        scaler = fit_scaler(train)
        X_train, column_names = encode_rows(train, vocabulary, scaler)
        X_val, _ = encode_rows(val, vocabulary, scaler)
        selected_folds.append(
            FoldData(
                X_train=X_train,
                X_val=X_val,
                y_train=np.asarray([r.y for r in train], dtype=np.int_),
                y_val=np.asarray([r.y for r in val], dtype=np.int_),
                column_names=column_names,
            )
        )
    return selected_folds


def score_folds(
    folds: Sequence[FoldData],
    predict: Callable[[FoldData], FloatArray],
) -> dict[str, object]:
    """Score out-of-fold predictions from any estimator family under the locked protocol.

    ``predict`` receives one fold and returns P(goal) for that fold's **validation** rows; it is
    the only model-specific part. Everything downstream — per-fold metrics, the unweighted mean,
    the pooled block, the reliability table and the D11 support summary — is shared.
    """
    fold_pairs: list[tuple[IntArray, FloatArray]] = [(fold.y_val, predict(fold)) for fold in folds]
    return finalize_metrics(evaluate_probability_scores(fold_pairs))


def restrict_folds(folds: Sequence[FoldData], columns_to_keep: Sequence[int]) -> list[FoldData]:
    """Project every fold onto a column subset, carrying the matching column names."""
    keep = list(columns_to_keep)
    return [
        FoldData(
            X_train=fold.X_train[:, keep],
            X_val=fold.X_val[:, keep],
            y_train=fold.y_train,
            y_val=fold.y_val,
            column_names=[fold.column_names[i] for i in keep],
        )
        for fold in folds
    ]


def mean_brier(metrics: Mapping[str, object]) -> float:
    per_fold = cast(Sequence[PerFoldMetrics], metrics["per_fold"])
    return float(np.mean([entry["brier"] for entry in per_fold]))


def replacement_rule(incumbent: Mapping[str, object], candidate: Mapping[str, object]) -> bool:
    """PLAN §4.1: all four conditions must hold on the development folds, never on the holdout."""
    incumbent_r = cast(_RuleMetrics, incumbent)
    candidate_r = cast(_RuleMetrics, candidate)
    return (
        candidate_r["mean_log_loss"]
        < incumbent_r["mean_log_loss"] - incumbent_r["sd_log_loss_ddof0"]
        and mean_brier(candidate) <= mean_brier(incumbent)
        and candidate_r["max_abs_deviation_supported"] <= incumbent_r["max_abs_deviation_supported"]
        and candidate_r["sd_log_loss_ddof0"] <= incumbent_r["sd_log_loss_ddof0"]
    )


def run_replacement_chain(
    candidates: Mapping[str, Mapping[str, object]],
    order: Sequence[str],
) -> tuple[list[bool], str]:
    """Walk an ordered candidate list, each step compared against the **running** incumbent.

    ``order[0]`` is the starting incumbent. Returns one boolean per comparison (so
    ``len(order) - 1`` of them, in order) and the incumbent that survives the chain.

    This generalises WP2.4's fixed three-step chain so WP2.5 can extend it by one step without
    re-specifying it. The rule applied at each step is unchanged.
    """
    if len(order) < 2:
        raise ValueError(f"a replacement chain needs at least two candidates, got {list(order)}")
    incumbent = order[0]
    outcomes: list[bool] = []
    for candidate in order[1:]:
        beats = replacement_rule(candidates[incumbent], candidates[candidate])
        outcomes.append(beats)
        if beats:
            incumbent = candidate
    return outcomes, incumbent
