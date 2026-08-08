"""Locked WP2.6 feature preparation, OOF scoring and replacement chains."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import torch

from touchline.modeling.boosting import BoostingParams, fit_boosting
from touchline.modeling.logistic import fit_logistic
from touchline.modeling.metrics import evaluate_probability_scores
from touchline.modeling.mlp import EPOCHS, EpochHistory, fit_mlp, predict_probabilities
from touchline.modeling.preprocessing import (
    CATEGORICAL_FIELDS,
    CONTINUOUS_FIELDS,
    PRESENCE_SOURCE_FIELDS,
    RARE_MIN_DEV_ROWS,
    ShotRow,
    Vocabulary,
    fit_vocabulary,
)
from touchline.modeling.protocol import (
    FoldData,
    build_folds,
    evaluate_constant,
    finalize_metrics,
    replacement_rule,
    restrict_folds,
    run_replacement_chain,
    score_folds,
)

MLP_KEY = "pytorch_mlp"
SHIPPED_LOGISTIC_KEY = "full_minus_presence"
GBM_KEY = "hist_gbm"
CHAIN_A_ORDER = (
    "constant",
    "geometry_logistic",
    SHIPPED_LOGISTIC_KEY,
    GBM_KEY,
    MLP_KEY,
)
SHIPPED_FEATURE_COLUMNS = (
    "distance_to_goal",
    "visible_goal_angle",
    "body_part_name::Head",
    "body_part_name::Left Foot",
    "body_part_name::rare",
    "technique_name::Half Volley",
    "technique_name::Volley",
    "technique_name::rare",
    "play_pattern_name::From Corner",
    "play_pattern_name::From Counter",
    "play_pattern_name::From Free Kick",
    "play_pattern_name::From Goal Kick",
    "play_pattern_name::From Keeper",
    "play_pattern_name::From Kick Off",
    "play_pattern_name::From Throw In",
    "play_pattern_name::rare",
)
INCUMBENT_LOGISTIC_C = 0.1
SELECTED_BOOSTING_PARAMS = BoostingParams(
    learning_rate=0.03,
    max_leaf_nodes=7,
    min_samples_leaf=60,
)


@dataclass(frozen=True)
class PreparedFolds:
    vocabulary: Vocabulary
    all_columns: tuple[str, ...]
    selected_columns: tuple[str, ...]
    selected_indices: tuple[int, ...]
    all_folds: tuple[FoldData, ...]
    folds: tuple[FoldData, ...]


@dataclass(frozen=True)
class MlpOofResult:
    metrics: dict[str, object]
    probabilities_by_fold: tuple[np.ndarray, ...]
    histories: tuple[tuple[EpochHistory, ...], ...]
    parameter_digests: tuple[str, ...]


def build_vocabulary(rows: Sequence[ShotRow]) -> Vocabulary:
    """Fit the inherited development-wide, label-free vocabulary."""
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        for field in CATEGORICAL_FIELDS:
            key = (field, str(getattr(row, field)))
            counts[key] = counts.get(key, 0) + 1
    return fit_vocabulary(counts, threshold=RARE_MIN_DEV_ROWS)


def prepare_shipped_folds(rows: Sequence[ShotRow], n_folds: int) -> PreparedFolds:
    """Build fold-training scalers and select the exact shipped 16 columns by name."""
    vocabulary = build_vocabulary(rows)
    all_columns = tuple(vocabulary.column_names())
    if len(all_columns) != len(set(all_columns)):
        raise ValueError("encoded development columns are not unique")
    missing = [name for name in SHIPPED_FEATURE_COLUMNS if name not in all_columns]
    if missing:
        raise ValueError(f"WP2.6 exact shipped feature contract is missing columns: {missing}")
    presence = {f"{field}_presence" for field in PRESENCE_SOURCE_FIELDS}
    selected_indices = tuple(
        index for index, name in enumerate(all_columns) if name not in presence
    )
    selected_columns = tuple(all_columns[index] for index in selected_indices)
    if selected_columns != SHIPPED_FEATURE_COLUMNS:
        raise ValueError(
            "WP2.6 encoded columns differ from the pre-registered 16-column shipped feature set"
        )
    all_folds = tuple(build_folds(rows, vocabulary, n_folds))
    folds = tuple(restrict_folds(all_folds, selected_indices))
    return PreparedFolds(
        vocabulary=vocabulary,
        all_columns=all_columns,
        selected_columns=selected_columns,
        selected_indices=selected_indices,
        all_folds=all_folds,
        folds=folds,
    )


def run_mlp_oof(
    folds: Sequence[FoldData], *, device: torch.device, epochs: int = EPOCHS
) -> MlpOofResult:
    """Fit a freshly reseeded MLP per outer fold and score epoch-final probabilities only."""
    fold_pairs: list[tuple[np.ndarray, np.ndarray]] = []
    probabilities: list[np.ndarray] = []
    histories: list[tuple[EpochHistory, ...]] = []
    parameter_digests: list[str] = []
    for fold in folds:
        if tuple(fold.column_names) != SHIPPED_FEATURE_COLUMNS:
            raise ValueError("MLP fold does not carry the exact 16 shipped columns")
        fit = fit_mlp(
            fold.X_train,
            fold.y_train,
            fold.X_val,
            fold.y_val,
            device=device,
            epochs=epochs,
        )
        predicted = predict_probabilities(fit.model, fold.X_val, device)
        fold_pairs.append((fold.y_val, predicted))
        probabilities.append(predicted)
        histories.append(fit.history)
        parameter_digests.append(fit.parameter_digest)
    metrics = finalize_metrics(evaluate_probability_scores(fold_pairs))
    return MlpOofResult(
        metrics=metrics,
        probabilities_by_fold=tuple(probabilities),
        histories=tuple(histories),
        parameter_digests=tuple(parameter_digests),
    )


def _score_logistic(folds: Sequence[FoldData]) -> dict[str, object]:
    def predict(fold: FoldData) -> np.ndarray:
        return fit_logistic(
            fold.X_train, fold.y_train, INCUMBENT_LOGISTIC_C, random_state=0
        ).predict_proba(fold.X_val)

    metrics = score_folds(folds, predict)
    metrics["best_c"] = INCUMBENT_LOGISTIC_C
    return metrics


def _score_booster(folds: Sequence[FoldData]) -> dict[str, object]:
    def predict(fold: FoldData) -> np.ndarray:
        return fit_boosting(
            fold.X_train, fold.y_train, SELECTED_BOOSTING_PARAMS, random_state=0
        ).predict_proba(fold.X_val)

    metrics = score_folds(folds, predict)
    metrics["hyperparameters"] = SELECTED_BOOSTING_PARAMS.as_dict()
    return metrics


def reproduce_inherited_candidates(
    rows: Sequence[ShotRow], prepared: PreparedFolds
) -> dict[str, Mapping[str, object]]:
    """Refit the four WP2.4 candidates and WP2.5 selected booster, with no grid rerun."""
    geometry_indices = [prepared.all_columns.index(name) for name in CONTINUOUS_FIELDS]
    presence = {f"{field}_presence" for field in PRESENCE_SOURCE_FIELDS}
    full_indices = list(range(len(prepared.all_columns)))
    minus_indices = [i for i, name in enumerate(prepared.all_columns) if name not in presence]
    return {
        "constant": evaluate_constant(rows, len(prepared.folds)),
        "geometry_logistic": _score_logistic(restrict_folds(prepared.all_folds, geometry_indices)),
        "full_logistic": _score_logistic(restrict_folds(prepared.all_folds, full_indices)),
        SHIPPED_LOGISTIC_KEY: _score_logistic(restrict_folds(prepared.all_folds, minus_indices)),
        GBM_KEY: _score_booster(prepared.folds),
    }


def selection_chains(
    candidates: Mapping[str, Mapping[str, object]],
) -> dict[str, Mapping[str, object]]:
    """Apply inherited Chain A for continuity and direct Chain B as the decision of record."""
    outcomes, protocol_incumbent = run_replacement_chain(candidates, CHAIN_A_ORDER)
    mlp_replaces = replacement_rule(candidates[SHIPPED_LOGISTIC_KEY], candidates[MLP_KEY])
    return {
        "chain_a": {
            "order": list(CHAIN_A_ORDER),
            "outcomes": outcomes,
            "protocol_incumbent": protocol_incumbent,
            "decision_role": "continuity_only",
        },
        "chain_b": {
            "incumbent": SHIPPED_LOGISTIC_KEY,
            "candidate": MLP_KEY,
            "candidate_replaces_incumbent": mlp_replaces,
            "selection_incumbent": MLP_KEY if mlp_replaces else SHIPPED_LOGISTIC_KEY,
        },
    }


def assert_metrics_reproduce_to_12_decimals(
    actual: Mapping[str, object], expected: Mapping[str, object], path: str = "candidate"
) -> None:
    """Fail on any historical numeric metric that differs after twelve-decimal rounding."""
    for key, expected_value in expected.items():
        if key not in actual:
            raise ValueError(f"historical reproduction missing published key {path}.{key}")
        actual_value = actual[key]
        current_path = f"{path}.{key}"
        _assert_reproduced_value(actual_value, expected_value, current_path)


def _assert_reproduced_value(actual: object, expected: object, path: str) -> None:
    if isinstance(expected, Mapping):
        if not isinstance(actual, Mapping):
            raise ValueError(f"historical reproduction type mismatch at {path}")
        assert_metrics_reproduce_to_12_decimals(actual, expected, path)
        return
    if isinstance(expected, list):
        if not isinstance(actual, list):
            raise ValueError(f"historical reproduction type mismatch at {path}")
        if len(actual) != len(expected):
            raise ValueError(
                f"historical reproduction list length mismatch at {path}: "
                f"{len(actual)} != {len(expected)}"
            )
        for index, (left, right) in enumerate(zip(actual, expected, strict=True)):
            _assert_reproduced_value(left, right, f"{path}[{index}]")
        return
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            raise ValueError(f"historical reproduction numeric type mismatch at {path}")
        if round(float(actual), 12) != round(float(expected), 12):
            raise ValueError(
                f"historical reproduction mismatch at {path}: "
                f"{actual!r} != {expected!r} to 12 decimals"
            )
        return
    if actual != expected:
        raise ValueError(f"historical reproduction mismatch at {path}: {actual!r} != {expected!r}")
