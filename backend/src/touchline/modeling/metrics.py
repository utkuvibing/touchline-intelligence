"""Probability-quality metrics for the WP2.4 evaluation protocol (WP2.3 restated).

Every metric here is defined exactly, because the WP2.4 evidence report is a portfolio artifact and
a misunderstanding about what a number *means* is worse than the number being small.

- Log loss uses a pre-registered clip ``ε = 1e-15`` so a probability of exactly 0 or 1 contributes
  ``-ln(ε)`` instead of ``inf``. The clip is part of the contract, not a coincidence.
- Brier is the mean squared error between the label and the probability.
- **PR AUC is defined exactly as ``sklearn.metrics.average_precision_score``** — the weighted sum
  of precision over recall steps — NOT the trapezoidal area under the interpolated PR curve
  (``sklearn.metrics.auc(recall, precision)``). The two differ, and the trapezoidal form is
  misleading for proper scoring-style reporting.
- **Single-class folds fail loudly.** ROC AUC and PR AUC are undefined when a fold's labels are all
  one value; a named error is raised rather than a degenerate number being reported.
- The reliability table is a locked object: **exactly five equal-width bins** fixed a priori
  (ADR 0004 amendment), left-closed and right-open with the last bin closed, so a prediction of
  exactly 1.0 lands in the fifth bin and a prediction of exactly 0.2 lands in the second. Empty
  bins are reported as empty (count 0, rates None), never dropped.

Canonical serialization (``canonical_metrics_json``) is the locked way to write ``metrics.json``:
sorted keys, deterministic separators, ``allow_nan=False``, an LF final newline, and finite metrics
rounded to 12 decimal places. Byte-identical output is required only under the same recorded
runtime fingerprint (git commit, source commit, sklearn/numpy versions, locked ``uv.lock``); a
documented numeric tolerance is used for cross-platform comparison.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any, TypedDict

import numpy as np
import numpy.typing as npt
from sklearn.metrics import average_precision_score, roc_auc_score  # type: ignore[import-untyped]

#: Pre-registered log-loss clip (WP2.4 contract). A perfectly confident wrong prediction costs
#: ``-ln(LOG_CLIP)`` rather than an infinite score.
LOG_CLIP = 1e-15

#: Locked by WP2.3 and ADR 0004 (2026-08-04 amendment): five equal-width reliability bins.
N_RELIABILITY_BINS = 5

#: Locked serialization precision for all finite metrics (WP2.4 contract).
DECIMAL_PLACES = 12

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int_]


class SingleClassFoldError(ValueError):
    """A fold whose labels contain only one class, where a metric is undefined.

    ROC AUC and PR AUC cannot be computed from a single-class fold; reporting a value would be
    inventing evidence. The error names this explicitly so callers can classify it as a data
    condition rather than a bug to paper over.
    """


class PerFoldMetrics(TypedDict):
    fold: int
    log_loss: float
    brier: float
    roc_auc: float
    pr_auc: float


class PooledOOFMetrics(TypedDict):
    n: int
    positive_count: int
    prevalence: float
    log_loss: float
    brier: float
    roc_auc: float
    pr_auc: float


class ReliabilityEntry(TypedDict):
    bin: int
    lower: float
    upper: float
    count: int
    positive_count: int
    mean_prediction: float | None
    observed_rate: float | None


class EvaluationResult(TypedDict):
    per_fold: list[PerFoldMetrics]
    mean_log_loss: float
    sd_log_loss_ddof0: float
    pooled_oof: PooledOOFMetrics
    reliability: list[ReliabilityEntry]


def _as_float_arrays(
    y_true: Sequence[float] | IntArray,
    y_score: Sequence[float] | FloatArray,
) -> tuple[IntArray, FloatArray]:
    y = np.asarray(y_true, dtype=np.float64)
    p = np.asarray(y_score, dtype=np.float64)
    if y.ndim != 1 or p.ndim != 1:
        raise ValueError("labels and predictions must be one-dimensional")
    if y.shape != p.shape:
        raise ValueError(f"label/prediction length mismatch: {y.shape} vs {p.shape}")
    return y.astype(np.int_), p


def log_loss(y_true: Sequence[float] | IntArray, y_score: Sequence[float] | FloatArray) -> float:
    """Binary cross-entropy with the pre-registered ε clip.

    ``mean over i of -ln( clip( p(y_true_i = 1 | row_i), ε, 1 ) )`` — the mean negative log of the
    predicted probability of the observed class, clipped into ``[LOG_CLIP, 1]``. This
    event-probability form makes the boundary exact: a perfectly confident wrong prediction costs
    ``-ln(ε)`` exactly, because the event probability itself is clipped rather than the two terms
    being recomposed in floating point.
    """
    y, p = _as_float_arrays(y_true, y_score)
    event_p = np.where(y == 1, p, 1.0 - p)
    clipped = np.clip(event_p, LOG_CLIP, 1.0)
    return float(-np.mean(np.log(clipped)))


def brier_score(y_true: Sequence[float] | IntArray, y_score: Sequence[float] | FloatArray) -> float:
    """Mean squared error between the label and the probability: ``mean((y - p)**2)``."""
    y, p = _as_float_arrays(y_true, y_score)
    return float(np.mean((y - p) ** 2))


def _require_two_classes(y_true: IntArray) -> None:
    """Raise when a discrimination metric is undefined because the folds labels are one class."""
    classes = np.unique(y_true)
    if classes.size < 2:
        raise SingleClassFoldError(
            "discrimination metrics undefined on a single-class fold (label values: "
            f"{classes.tolist()})"
        )


def roc_auc(y_true: Sequence[float] | IntArray, y_score: Sequence[float] | FloatArray) -> float:
    """Receiver-operating-characteristic area under the curve (sklearn, guards single-class)."""
    y, p = _as_float_arrays(y_true, y_score)
    _require_two_classes(y)
    return float(roc_auc_score(y, p))


def pr_auc(y_true: Sequence[float] | IntArray, y_score: Sequence[float] | FloatArray) -> float:
    """PR AUC as ``sklearn.metrics.average_precision_score``, never trapezoidal.

    See the module docstring: the trapezoidal form is not used because it interpolates across
    precision drops and mis-reports the operating region.
    """
    y, p = _as_float_arrays(y_true, y_score)
    _require_two_classes(y)
    return float(average_precision_score(y, p))


def _bin_index(prediction: float) -> int:
    """Bin index in ``0..N_RELIABILITY_BINS-1`` for an equal-width [0, 1] grid.

    Width is ``1 / N_RELIABILITY_BINS``; the grid is left-closed/right-open with the last bin
    closed, so ``min(floor(p / width), N_RELIABILITY_BINS - 1)`` puts 1.0 in the last bin and 0.2
    in the second.
    """
    width = 1.0 / N_RELIABILITY_BINS
    return min(int(prediction // width), N_RELIABILITY_BINS - 1)


def reliability_table(
    y_true: Sequence[float] | IntArray,
    y_score: Sequence[float] | FloatArray,
    n_bins: int = N_RELIABILITY_BINS,
) -> list[ReliabilityEntry]:
    """Five equal-width-bin reliability table with counts; empty bins reported, never dropped.

    Each entry has: ``bin``, ``lower``, ``upper``, ``count``, ``mean_prediction``,
    ``observed_rate``, ``positive_count``. Empty bins carry ``count = 0`` and ``None`` rates so
    they are visibly empty rather than silently absent. Bins with adequate support (≥ 100 pooled
    out-of-fold predictions, contract condition D11) are the ones used for calibration comparison.
    """
    if n_bins != N_RELIABILITY_BINS:
        raise ValueError(
            f"reliability bin count is locked at {N_RELIABILITY_BINS} by ADR 0004; got {n_bins}"
        )
    y, p = _as_float_arrays(y_true, y_score)
    width = 1.0 / n_bins
    table: list[ReliabilityEntry] = []
    for index in range(n_bins):
        mask = np.array([_bin_index(float(x)) == index for x in p])
        count = int(mask.sum())
        entry: ReliabilityEntry = {
            "bin": index,
            "lower": round(index * width, 12),
            "upper": round((index + 1) * width, 12) if index < n_bins - 1 else 1.0,
            "count": count,
            "positive_count": int(y[mask].sum()) if count else 0,
            "mean_prediction": float(np.mean(p[mask])) if count else None,
            "observed_rate": float(np.mean(y[mask])) if count else None,
        }
        table.append(entry)
    return table


def round_metrics(value: Any, places: int = DECIMAL_PLACES) -> Any:
    """Deep-copy ``value`` rounding every finite float to ``places`` decimal places.

    Integers, strings, booleans and ``None`` are preserved. Non-finite floats (NaN/inf) are left
    untouched so the ``allow_nan=False`` serializer fails loudly on them afterwards.
    """
    if isinstance(value, float):
        return round(value, places) if math.isfinite(value) else value
    if isinstance(value, dict):
        return {key: round_metrics(item, places) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [round_metrics(item, places) for item in value]
    return value


def canonical_metrics_json(metrics: Mapping[str, Any]) -> bytes:
    """Serialize metrics to the locked canonical ``metrics.json`` form.

    Sorted keys, deterministic separators, ``allow_nan=False``, finite values rounded to 12
    decimal places, and a single LF final newline. The bytes are the reproducibility definition for
    the experiment record: identical only under the same recorded runtime fingerprint.
    """
    rounded = round_metrics(metrics)
    payload = json.dumps(
        rounded,
        sort_keys=True,
        indent=2,
        separators=(",", ": "),
        ensure_ascii=True,
        allow_nan=False,
    )
    return (payload + "\n").encode("utf-8")


def evaluate_probability_scores(
    fold_pairs: Sequence[tuple[Sequence[float] | IntArray, Sequence[float] | FloatArray]],
) -> EvaluationResult:
    """Evaluate one candidate over matched development folds, exactly as WP2.3 requires.

    ``fold_pairs`` is ``[(y_val, p_val) ...]`` for folds 0..4 in order. The aggregation contract
    pins three things that are easy to conflate:

    - ``per_fold`` — the five fold-level metric tables (each with log loss, Brier, ROC AUC,
      PR AUC), reported verbatim into ``metrics.json``;
    - ``mean_log_loss`` — the **unweighted arithmetic mean** of the five fold-level log losses
      (the candidate-comparison and C-selection quantity), and ``sd_log_loss_ddof0`` — the
      cross-fold standard deviation with ``ddof=0`` (stability);
    - ``pooled_oof`` — metrics computed over all out-of-fold predictions pooled together, reported
      separately and never conflated with the fold means (WP2.4 contract §9).

    The reliability table is computed on the pooled out-of-fold predictions. A single-class fold
    raises ``SingleClassFoldError`` loudly (discrimination metrics are undefined).
    """
    if not fold_pairs:
        raise ValueError("evaluate_probability_scores needs at least one fold")
    per_fold: list[PerFoldMetrics] = []
    pooled_y: list[float] = []
    pooled_p: list[float] = []
    for fold_index, (y_fold, p_fold) in enumerate(fold_pairs):
        y_values, p_values = _as_float_arrays(y_fold, p_fold)
        per_fold.append(
            {
                "fold": fold_index,
                "log_loss": log_loss(y_values, p_values),
                "brier": brier_score(y_values, p_values),
                "roc_auc": roc_auc(y_values, p_values),
                "pr_auc": pr_auc(y_values, p_values),
            }
        )
        pooled_y.extend(y_values.tolist())
        pooled_p.extend(p_values.tolist())

    y_pooled = np.asarray(pooled_y, dtype=np.int_)
    p_pooled = np.asarray(pooled_p, dtype=np.float64)
    fold_log_losses = [entry["log_loss"] for entry in per_fold]
    pooled_metrics: PooledOOFMetrics = {
        "n": int(y_pooled.size),
        "positive_count": int(y_pooled.sum()),
        "prevalence": float(y_pooled.mean()),
        "log_loss": log_loss(y_pooled, p_pooled),
        "brier": brier_score(y_pooled, p_pooled),
        "roc_auc": roc_auc(y_pooled, p_pooled),
        "pr_auc": pr_auc(y_pooled, p_pooled),
    }
    return {
        "per_fold": per_fold,
        "mean_log_loss": float(np.mean(fold_log_losses)),
        "sd_log_loss_ddof0": float(np.std(fold_log_losses, ddof=0)),
        "pooled_oof": pooled_metrics,
        "reliability": reliability_table(y_pooled, p_pooled),
    }
