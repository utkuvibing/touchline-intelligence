"""Fast unit contracts for the fixed WP2.6 model and explicit PyTorch loop."""

from __future__ import annotations

import inspect

import numpy as np
import pytest
import torch

import touchline.modeling.mlp as mlp_module
from touchline.modeling.mlp import (
    BATCH_SIZE,
    BETAS,
    EPOCHS,
    EPSILON,
    INPUT_DIM,
    LEARNING_RATE,
    PARAMETER_COUNT,
    SEED,
    WEIGHT_DECAY,
    ShotMLP,
    ShotTensorDataset,
    apply_ieee_fp32_policy,
    fit_mlp,
    predict_probabilities,
)


def _matrix(n: int = 24) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(9)
    x = rng.normal(size=(n, INPUT_DIM)).astype(np.float64)
    y = np.asarray([0, 1] * (n // 2), dtype=np.int_)
    return x, y


def test_dataset_owns_float32_tensors_with_one_label_per_row() -> None:
    x, y = _matrix()
    dataset = ShotTensorDataset(x, y)
    assert len(dataset) == len(y)
    features, target = dataset[3]
    assert features.shape == (16,)
    assert features.dtype == torch.float32
    assert target.shape == ()
    assert target.dtype == torch.float32


def test_fixed_architecture_returns_logits_and_has_exactly_145_parameters() -> None:
    model = ShotMLP()
    assert model(torch.zeros((4, 16), dtype=torch.float32)).shape == (4,)
    assert sum(parameter.numel() for parameter in model.parameters()) == PARAMETER_COUNT == 145
    assert isinstance(model.hidden, torch.nn.Linear)
    assert isinstance(model.activation, torch.nn.ReLU)
    assert isinstance(model.output, torch.nn.Linear)
    assert not any(
        isinstance(module, (torch.nn.Dropout, torch.nn.BatchNorm1d)) for module in model.modules()
    )
    source = inspect.getsource(ShotMLP.forward)
    assert "sigmoid" not in source


def test_ieee_policy_uses_only_the_pytorch_213_fp32_precision_family() -> None:
    apply_ieee_fp32_policy()
    assert torch.backends.fp32_precision == "ieee"  # type: ignore[attr-defined]
    assert torch.backends.cuda.matmul.fp32_precision == "ieee"
    assert torch.backends.cudnn.fp32_precision == "ieee"
    source = inspect.getsource(apply_ieee_fp32_policy)
    assert "allow_tf32" not in source
    assert "set_float32_matmul_precision" not in source


def test_training_loop_is_reproducible_consumes_every_row_and_records_losses() -> None:
    x, y = _matrix()
    first = fit_mlp(x, y, x, y, device=torch.device("cpu"), epochs=3)
    second = fit_mlp(x, y, x, y, device=torch.device("cpu"), epochs=3)
    assert first.history == second.history
    assert first.parameter_digest == second.parameter_digest
    assert len(first.history) == 3
    assert all(item.train_samples == len(y) for item in first.history)
    assert all(item.validation_samples == len(y) for item in first.history)
    assert all(
        np.isfinite(item.train_loss) and np.isfinite(item.validation_loss) for item in first.history
    )
    probabilities = predict_probabilities(first.model, x, torch.device("cpu"))
    assert probabilities.shape == (len(y),)
    assert np.all(np.isfinite(probabilities))
    assert np.all((probabilities >= 0.0) & (probabilities <= 1.0))


def test_training_contract_constants_are_fixed() -> None:
    assert EPOCHS == 200
    assert BATCH_SIZE == 128
    assert SEED == 0
    assert LEARNING_RATE == 1e-3
    assert WEIGHT_DECAY == 1e-4
    assert BETAS == (0.9, 0.999)
    assert EPSILON == 1e-8
    seed_source = inspect.getsource(mlp_module.reset_fit_seed)
    assert "torch.cuda.manual_seed_all(seed)" in seed_source


def test_loop_spells_out_optimizer_loader_autograd_and_modes() -> None:
    source = inspect.getsource(fit_mlp)
    for contract in (
        "BCEWithLogitsLoss",
        'reduction="mean"',
        "pos_weight=None",
        "torch.optim.AdamW",
        "lr=LEARNING_RATE",
        "weight_decay=WEIGHT_DECAY",
        "amsgrad=False",
        "foreach=False",
        "fused=False",
        "model.train()",
        "optimizer.zero_grad(set_to_none=True)",
        "loss.backward()",
        "optimizer.step()",
        "generator=generator",
    ):
        assert contract in source
    module_source = inspect.getsource(__import__("touchline.modeling.mlp", fromlist=["*"]))
    assert "early_stopping" not in module_source
    assert "scheduler" not in module_source
    assert "autocast" not in module_source
    assert "torch.compile" not in module_source
    evaluation_source = inspect.getsource(mlp_module._evaluate_loss)
    assert "model.eval()" in evaluation_source
    assert "with torch.no_grad()" in evaluation_source


def test_dataset_rejects_wrong_column_count_and_non_binary_targets() -> None:
    x, y = _matrix()
    with pytest.raises(ValueError, match="exactly 16"):
        ShotTensorDataset(x[:, :-1], y)
    bad = y.copy()
    bad[0] = 2
    with pytest.raises(ValueError, match="binary"):
        ShotTensorDataset(x, bad)
