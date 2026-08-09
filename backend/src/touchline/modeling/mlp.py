"""Fixed PyTorch estimator and explicit training loop for WP2.6.

This module has no database, experiment-record or serving imports. Importing it intentionally loads
PyTorch, so callers must opt into it directly; ``touchline.modeling`` and the API remain Torch-free.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from typing import cast

import numpy as np
import numpy.typing as npt
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset

INPUT_DIM = 16
HIDDEN_DIM = 8
PARAMETER_COUNT = 145
SEED = 0
EPOCHS = 200
BATCH_SIZE = 128
LEARNING_RATE = 1e-3
WEIGHT_DECAY = 1e-4
BETAS = (0.9, 0.999)
EPSILON = 1e-8
NUM_WORKERS = 0

FloatMatrix = npt.NDArray[np.float64]
IntVector = npt.NDArray[np.int_]
ProbabilityVector = npt.NDArray[np.float64]


class ShotTensorDataset(Dataset[tuple[torch.Tensor, torch.Tensor]]):
    """Owned float32 feature and binary-target tensors with one sample per index."""

    def __init__(self, features: npt.ArrayLike, targets: npt.ArrayLike) -> None:
        x = np.asarray(features)
        y = np.asarray(targets)
        if x.ndim != 2 or x.shape[1] != INPUT_DIM:
            raise ValueError(f"WP2.6 features must have exactly {INPUT_DIM} columns")
        if y.ndim != 1 or len(y) != len(x):
            raise ValueError("WP2.6 targets must be a one-dimensional vector aligned with features")
        if not np.all(np.isfinite(x)):
            raise ValueError("WP2.6 features must be finite")
        if not np.all(np.isin(y, (0, 1))):
            raise ValueError("WP2.6 targets must be binary 0/1 values")
        self.features = torch.tensor(x, dtype=torch.float32, device="cpu")
        self.targets = torch.tensor(y, dtype=torch.float32, device="cpu")

    def __len__(self) -> int:
        return int(self.targets.shape[0])

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        return self.features[index], self.targets[index]


class ShotMLP(nn.Module):
    """The pre-registered 16 -> 8 -> 1 network; ``forward`` returns raw logits."""

    def __init__(self) -> None:
        super().__init__()
        self.hidden = nn.Linear(INPUT_DIM, HIDDEN_DIM, bias=True, dtype=torch.float32)
        self.activation = nn.ReLU()
        self.output = nn.Linear(HIDDEN_DIM, 1, bias=True, dtype=torch.float32)
        nn.init.kaiming_uniform_(self.hidden.weight, a=0.0, mode="fan_in", nonlinearity="relu")
        nn.init.zeros_(self.hidden.bias)
        nn.init.xavier_uniform_(self.output.weight, gain=1.0)
        nn.init.zeros_(self.output.bias)

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return cast(torch.Tensor, self.output(self.activation(self.hidden(features))).squeeze(-1))


@dataclass(frozen=True)
class EpochHistory:
    epoch: int
    train_loss: float
    validation_loss: float
    train_samples: int
    validation_samples: int


@dataclass(frozen=True)
class FitResult:
    model: ShotMLP
    history: tuple[EpochHistory, ...]
    parameter_digest: str


def reset_fit_seed(seed: int = SEED) -> torch.Generator:
    """Reset every RNG before model creation and return the dedicated loader generator."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    generator = torch.Generator(device="cpu")
    generator.manual_seed(seed)
    return generator


def apply_ieee_fp32_policy() -> None:
    """Pin IEEE FP32 through PyTorch 2.13's current precision-control API family only."""
    torch.backends.fp32_precision = "ieee"  # type: ignore[attr-defined]
    torch.backends.cuda.matmul.fp32_precision = "ieee"
    torch.backends.cudnn.fp32_precision = "ieee"


def configure_deterministic_runtime() -> None:
    """Apply process-wide deterministic and thread policy before any fit."""
    torch.use_deterministic_algorithms(True, warn_only=False)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    apply_ieee_fp32_policy()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)


def _loader(
    dataset: ShotTensorDataset,
    *,
    shuffle: bool,
    generator: torch.Generator | None,
) -> DataLoader[tuple[torch.Tensor, torch.Tensor]]:
    return DataLoader(
        dataset,
        batch_size=BATCH_SIZE,
        shuffle=shuffle,
        num_workers=NUM_WORKERS,
        pin_memory=False,
        drop_last=False,
        generator=generator,
        persistent_workers=False,
    )


def _assert_finite_model(model: ShotMLP) -> None:
    for name, parameter in model.named_parameters():
        if not bool(torch.isfinite(parameter).all().item()):
            raise FloatingPointError(f"non-finite parameter after optimizer step: {name}")


def _evaluate_loss(
    model: ShotMLP,
    loader: DataLoader[tuple[torch.Tensor, torch.Tensor]],
    criterion: nn.BCEWithLogitsLoss,
    device: torch.device,
) -> tuple[float, int]:
    model.eval()
    loss_sum = 0.0
    samples = 0
    with torch.no_grad():
        for features, targets in loader:
            features = features.to(device=device, dtype=torch.float32, non_blocking=False)
            targets = targets.to(device=device, dtype=torch.float32, non_blocking=False)
            logits = model(features)
            if not bool(torch.isfinite(logits).all().item()):
                raise FloatingPointError("non-finite validation logits")
            loss = criterion(logits, targets)
            batch_size = int(targets.shape[0])
            loss_sum += float(loss.detach().cpu().item()) * batch_size
            samples += batch_size
    return loss_sum / samples, samples


def fit_mlp(
    train_features: npt.ArrayLike,
    train_targets: npt.ArrayLike,
    validation_features: npt.ArrayLike,
    validation_targets: npt.ArrayLike,
    *,
    device: torch.device,
    epochs: int = EPOCHS,
) -> FitResult:
    """Fit one newly seeded model and return the complete diagnostic loss history."""
    if epochs <= 0:
        raise ValueError("epochs must be positive")
    generator = reset_fit_seed(SEED)
    model = ShotMLP().to(device=device, dtype=torch.float32)
    training = ShotTensorDataset(train_features, train_targets)
    validation = ShotTensorDataset(validation_features, validation_targets)
    train_loader = _loader(training, shuffle=True, generator=generator)
    validation_loader = _loader(validation, shuffle=False, generator=None)
    criterion = nn.BCEWithLogitsLoss(weight=None, reduction="mean", pos_weight=None)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=LEARNING_RATE,
        betas=BETAS,
        eps=EPSILON,
        weight_decay=WEIGHT_DECAY,
        amsgrad=False,
        foreach=False,
        maximize=False,
        capturable=False,
        differentiable=False,
        fused=False,
    )
    history: list[EpochHistory] = []
    for epoch in range(1, epochs + 1):
        model.train()
        loss_sum = 0.0
        samples = 0
        for features, targets in train_loader:
            features = features.to(device=device, dtype=torch.float32, non_blocking=False)
            targets = targets.to(device=device, dtype=torch.float32, non_blocking=False)
            optimizer.zero_grad(set_to_none=True)
            logits = model(features)
            loss = criterion(logits, targets)
            if not bool(torch.isfinite(loss).item()):
                raise FloatingPointError("non-finite training loss")
            loss.backward()
            for name, parameter in model.named_parameters():
                if parameter.grad is None or not bool(torch.isfinite(parameter.grad).all().item()):
                    raise FloatingPointError(f"missing or non-finite gradient: {name}")
            optimizer.step()
            _assert_finite_model(model)
            batch_size = int(targets.shape[0])
            loss_sum += float(loss.detach().cpu().item()) * batch_size
            samples += batch_size
        validation_loss, validation_samples = _evaluate_loss(
            model, validation_loader, criterion, device
        )
        train_loss = loss_sum / samples
        if not math.isfinite(train_loss) or not math.isfinite(validation_loss):
            raise FloatingPointError("non-finite epoch loss")
        history.append(
            EpochHistory(
                epoch=epoch,
                train_loss=train_loss,
                validation_loss=validation_loss,
                train_samples=samples,
                validation_samples=validation_samples,
            )
        )
    return FitResult(model=model, history=tuple(history), parameter_digest=parameter_digest(model))


def predict_probabilities(
    model: ShotMLP, features: npt.ArrayLike, device: torch.device
) -> ProbabilityVector:
    """Apply sigmoid exactly once to ordered logits and return float64 probabilities."""
    matrix = np.asarray(features)
    if matrix.ndim != 2 or matrix.shape[1] != INPUT_DIM:
        raise ValueError(f"WP2.6 features must have exactly {INPUT_DIM} columns")
    tensor = torch.tensor(matrix, dtype=torch.float32, device=device)
    model.eval()
    with torch.no_grad():
        logits = model(tensor)
        probabilities = torch.sigmoid(logits)
    if not bool(torch.isfinite(probabilities).all().item()):
        raise FloatingPointError("non-finite probabilities")
    return probabilities.detach().cpu().numpy().astype(np.float64, copy=False)


def parameter_digest(model: ShotMLP) -> str:
    """Content identity over sorted tensor name, dtype, shape and contiguous CPU bytes."""
    digest = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        contiguous = tensor.detach().to(device="cpu").contiguous()
        for value in (name, str(contiguous.dtype), repr(tuple(contiguous.shape))):
            encoded = value.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        raw = contiguous.numpy().tobytes(order="C")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def cpu_cuda_inference_parity(
    canonical_cpu_model: ShotMLP,
    features: npt.ArrayLike,
    *,
    atol: float = 1e-6,
    rtol: float = 1e-5,
) -> dict[str, float]:
    """Score identical canonical weights on CPU/CUDA and enforce the qualification tolerance."""
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA inference parity was requested but CUDA is unavailable")
    cpu_model = ShotMLP().to(device="cpu", dtype=torch.float32)
    cpu_model.load_state_dict(canonical_cpu_model.state_dict(), strict=True)
    cuda_model = ShotMLP().to(device="cuda:0", dtype=torch.float32)
    cuda_model.load_state_dict(canonical_cpu_model.state_dict(), strict=True)
    cpu_probabilities = predict_probabilities(cpu_model, features, torch.device("cpu"))
    cuda_probabilities = predict_probabilities(cuda_model, features, torch.device("cuda:0"))
    difference = np.abs(cpu_probabilities - cuda_probabilities)
    if not np.allclose(cpu_probabilities, cuda_probabilities, atol=atol, rtol=rtol):
        raise RuntimeError(
            f"CPU/CUDA same-weight inference parity failed: max difference {difference.max()}"
        )
    return {
        "atol": atol,
        "rtol": rtol,
        "mean_probability_difference": float(difference.mean()),
        "max_probability_difference": float(difference.max()),
    }
