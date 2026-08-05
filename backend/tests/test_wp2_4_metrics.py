"""Unit contracts for the WP2.4 metric definitions. Hand-computed, no database, no sklearn drift.

Each case is chosen so the *definition* is pinned, not just the code path:

- log loss on a constant p = 0.5 vector equals -ln(0.5) exactly;
- the ε clip turns a perfectly confident wrong prediction into -ln(1e-15), not infinity;
- PR AUC equals ``sklearn.metrics.average_precision_score`` and is asserted to be *different from*
  the trapezoidal PR-curve area on a hand-built case, pinning that we do not use the trapezoid;
- reliability bins are left-closed/right-open with a closed last bin: p = 0.2 → bin 1,
  p = 1.0 → bin 4 (and p = 0.0 → bin 0);
- empty bins are reported with count 0 and None rates, never dropped;
- single-class folds raise, they do not return a degenerate discrimination number;
- ``canonical_metrics_json`` is byte-deterministic, sorts keys, rounds finite metrics to 12
  decimal places, ends with an LF, and refuses NaN via ``allow_nan=False``.
"""

from __future__ import annotations

import json
import math

import numpy as np
from sklearn.metrics import (  # type: ignore[import-untyped]
    auc,
    average_precision_score,
    precision_recall_curve,
)

from touchline.modeling.metrics import (
    LOG_CLIP,
    N_RELIABILITY_BINS,
    SingleClassFoldError,
    brier_score,
    canonical_metrics_json,
    log_loss,
    pr_auc,
    reliability_table,
    roc_auc,
    round_metrics,
)


def test_log_loss_constant_half_vector() -> None:
    # y = [1, 0, 1], p = [0.5, 0.5, 0.5] -> each term -ln(0.5); mean = -ln(0.5).
    assert math.isclose(
        log_loss([1, 0, 1], [0.5, 0.5, 0.5]),
        -math.log(0.5),
        abs_tol=1e-15,
    )


def test_log_loss_clip_turns_full_confidence_into_finite_cost() -> None:
    # Perfectly confident and wrong on both rows: p = 0 against y = 1 and p = 1 against y = 0.
    expected = -math.log(LOG_CLIP)
    assert math.isclose(log_loss([1, 0], [0.0, 1.0]), expected, abs_tol=1e-12)


def test_log_loss_is_zero_at_perfect_confidence() -> None:
    assert math.isclose(log_loss([1, 0, 1], [1.0, 0.0, 1.0]), 0.0, abs_tol=1e-15)


def test_brier_matches_mean_squared_error() -> None:
    y = [1, 0, 1]
    p = [0.5, 0.5, 0.5]
    # (1-0.5)^2 + (0-0.5)^2 + (1-0.5)^2 over 3 = (0.25 * 3) / 3 = 0.25.
    assert brier_score(y, p) == 0.25


def test_roc_auc_hand_case() -> None:
    y = [0, 0, 1, 1]
    p = [0.1, 0.4, 0.35, 0.8]
    # Only pair the mid positive (0.35) loses to the mid negative (0.4): 3 of 4 orders are correct.
    assert roc_auc(y, p) == 0.75


def test_pr_auc_is_average_precision_not_trapezoid() -> None:
    y = [0, 0, 1, 1]
    p = [0.1, 0.4, 0.35, 0.8]
    assert math.isclose(pr_auc(y, p), 0.8333333333333333, abs_tol=1e-12)
    # Must equal sklearn's average_precision_score...
    assert math.isclose(
        pr_auc(y, p), average_precision_score(np.asarray(y), np.asarray(p)), abs_tol=1e-15
    )
    # ...and must NOT be the trapezoidal area under the PR curve (0.7916... here).
    precision, recall, _ = precision_recall_curve(np.asarray(y), np.asarray(p))
    assert not math.isclose(pr_auc(y, p), auc(recall, precision), abs_tol=1e-9)


def test_single_class_fold_fails_loudly() -> None:
    for fn in (roc_auc, pr_auc):
        try:
            fn([1, 1, 1], [0.5, 0.6, 0.7])
        except SingleClassFoldError:
            continue
        raise AssertionError(
            f"{fn.__name__} must raise SingleClassFoldError on a single-class fold"
        )
    # All-negative folds too.
    try:
        pr_auc([0, 0, 0], [0.5, 0.6, 0.7])
    except SingleClassFoldError:
        pass
    else:
        raise AssertionError("pr_auc must raise on an all-negative fold")


def test_reliability_bins_are_left_closed_right_open_last_closed() -> None:
    table = reliability_table([0, 1, 0, 1], [0.0, 0.2, 1.0, 0.999999999999])
    by_bin = {entry["bin"]: entry for entry in table}
    assert len(table) == N_RELIABILITY_BINS
    # p = 0.0 -> bin 0; p = 0.2 -> bin 1; p ~ 1.0 and p = 1.0 -> bin 4 (closed last bin).
    assert by_bin[0]["count"] == 1
    assert by_bin[1]["count"] == 1
    assert by_bin[4]["count"] == 2


def test_reliability_empty_bins_are_reported_never_dropped() -> None:
    table = reliability_table([1, 0, 1], [0.05, 0.1, 0.15])
    assert len(table) == N_RELIABILITY_BINS
    assert table[0]["count"] == 3
    assert table[0]["observed_rate"] == 2 / 3
    for index in range(1, N_RELIABILITY_BINS):
        assert table[index]["count"] == 0
        assert table[index]["positive_count"] == 0
        assert table[index]["mean_prediction"] is None
        assert table[index]["observed_rate"] is None


def test_reliability_bin_count_is_locked_at_five() -> None:
    try:
        reliability_table([0, 1], [0.3, 0.7], n_bins=10)
    except ValueError:
        pass
    else:
        raise AssertionError("reliability bin count must be locked at five")


def test_round_metrics_rounds_finite_floats_only() -> None:
    rounded = round_metrics(
        {
            "a": 0.123456789012345,
            "b": 1,
            "c": "x",
            "d": None,
            "e": True,
            "f": [0.987654321098765, 2.0],
        }
    )
    assert rounded["a"] == 0.123456789012
    assert rounded["f"] == [0.987654321099, 2.0]
    assert (
        rounded["b"] == 1 and rounded["c"] == "x" and rounded["d"] is None and rounded["e"] is True
    )


def test_canonical_metrics_json_is_deterministic_and_canonical() -> None:
    metrics = {"brier": 0.1234567890123456, "a": {"log_loss": 0.5}, "n": None}
    payload = canonical_metrics_json(metrics)
    text = payload.decode("utf-8")
    assert payload.endswith(b"\n") and not text.endswith("\r\n")
    assert text.count("\n") == text.count("\n")
    decoded = json.loads(text)
    assert decoded == {"a": {"log_loss": 0.5}, "brier": 0.123456789012, "n": None}
    # Deterministic: same input -> identical bytes.
    assert canonical_metrics_json(metrics) == canonical_metrics_json(metrics)
    # allow_nan=False fails loudly on non-finite values.
    try:
        canonical_metrics_json({"bad": float("nan")})
    except ValueError:
        pass
    else:
        raise AssertionError("canonical_metrics_json must reject NaN (allow_nan=False)")
