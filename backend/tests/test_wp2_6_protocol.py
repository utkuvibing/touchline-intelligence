"""WP2.6 OOF protocol, exact feature contract and selection-chain tests."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import cast

import numpy as np
import pytest
import torch
from support.wp26_synthetic import wp26_rows

from touchline.modeling.mlp_protocol import (
    MLP_KEY,
    SHIPPED_FEATURE_COLUMNS,
    assert_metrics_reproduce_to_12_decimals,
    prepare_shipped_folds,
    run_mlp_oof,
    selection_chains,
)
from touchline.modeling.train_mlp import run_protocol


def test_exact_shipped_columns_exclude_presence_and_are_shared_across_folds() -> None:
    prepared = prepare_shipped_folds(wp26_rows(), n_folds=5)
    assert prepared.selected_columns == SHIPPED_FEATURE_COLUMNS
    assert len(prepared.selected_columns) == 16
    assert all("presence" not in name for name in prepared.selected_columns)
    assert all(fold.column_names == list(SHIPPED_FEATURE_COLUMNS) for fold in prepared.folds)
    assert [len(fold.y_val) for fold in prepared.folds] == [80] * 5


def test_mlp_oof_scores_only_validation_rows_at_the_fixed_last_epoch() -> None:
    prepared = prepare_shipped_folds(wp26_rows(), n_folds=5)
    result = run_mlp_oof(prepared.folds, device=torch.device("cpu"), epochs=2)
    pooled = cast(Mapping[str, object], result.metrics["pooled_oof"])
    assert pooled["n"] == 400
    assert len(result.probabilities_by_fold) == 5
    assert all(len(values) == 80 for values in result.probabilities_by_fold)
    assert all(len(history) == 2 and history[-1].epoch == 2 for history in result.histories)
    assert len(result.parameter_digests) == 5
    assert np.isfinite(float(cast(float, result.metrics["mean_log_loss"])))


def test_chain_b_is_direct_logistic_vs_mlp_and_chain_a_is_continuity_only() -> None:
    weak = {
        "mean_log_loss": 1.0,
        "sd_log_loss_ddof0": 0.2,
        "max_abs_deviation_supported": 1.0,
        "per_fold": [{"brier": 1.0}],
    }
    strong = {
        "mean_log_loss": 0.1,
        "sd_log_loss_ddof0": 0.01,
        "max_abs_deviation_supported": 0.1,
        "per_fold": [{"brier": 0.1}],
    }
    unbeatable_constant = {
        "mean_log_loss": 0.05,
        "sd_log_loss_ddof0": 0.001,
        "max_abs_deviation_supported": 0.01,
        "per_fold": [{"brier": 0.01}],
    }
    candidates = {
        "constant": unbeatable_constant,
        "geometry_logistic": weak,
        "full_minus_presence": weak,
        "hist_gbm": weak,
        MLP_KEY: strong,
    }
    chains = selection_chains(candidates)
    assert chains["chain_a"]["order"] == [
        "constant",
        "geometry_logistic",
        "full_minus_presence",
        "hist_gbm",
        "pytorch_mlp",
    ]
    assert chains["chain_b"] == {
        "incumbent": "full_minus_presence",
        "candidate": "pytorch_mlp",
        "candidate_replaces_incumbent": True,
        "selection_incumbent": "pytorch_mlp",
    }


def test_final_all_development_scaler_is_structurally_after_frozen_oof_selection() -> None:
    source = inspect.getsource(run_protocol)
    assert source.index("chains = selection_chains(candidates)") < source.index(
        "final_scaler = fit_scaler(rows_list)"
    )
    assert "Selection is now frozen" in source


def test_historical_reproduction_rejects_missing_keys_and_list_shape_changes() -> None:
    with pytest.raises(ValueError, match="missing published key"):
        assert_metrics_reproduce_to_12_decimals({}, {"mean_log_loss": 0.2})
    with pytest.raises(ValueError, match="list length"):
        assert_metrics_reproduce_to_12_decimals(
            {"per_fold": [{"fold": 0}]},
            {"per_fold": [{"fold": 0}, {"fold": 1}]},
        )
