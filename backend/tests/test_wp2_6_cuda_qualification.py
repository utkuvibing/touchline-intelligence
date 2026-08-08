"""Local RTX qualification: full five-fold + final-refit repeats and same-weight parity."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import torch
from support.wp26_synthetic import wp26_rows

from touchline.modeling.mlp import cpu_cuda_inference_parity
from touchline.modeling.preprocessing import encode_rows
from touchline.modeling.train_mlp import run_protocol

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.cuda
def test_cuda_runs_all_folds_and_final_refit_twice_in_fresh_processes() -> None:
    if not torch.cuda.is_available():
        pytest.skip("CUDA qualification requires a local CUDA-capable locked Torch environment")
    environment = dict(os.environ)
    environment["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    environment["PYTHONPATH"] = str(ROOT / "backend/tests")
    first = subprocess.run(
        [sys.executable, "-m", "support.wp26_cuda_probe"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    second = subprocess.run(
        [sys.executable, "-m", "support.wp26_cuda_probe"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first.stdout == second.stdout


@pytest.mark.cuda
def test_same_canonical_weights_have_cpu_cuda_probability_parity() -> None:
    if not torch.cuda.is_available():
        pytest.skip("CUDA qualification requires a local CUDA-capable locked Torch environment")
    rows = wp26_rows()
    cpu = run_protocol(rows, device=torch.device("cpu"), published_metrics_path=None, epochs=2)
    full, _ = encode_rows(rows, cpu.prepared.vocabulary, cpu.final_scaler)
    selected = full[:, list(cpu.prepared.selected_indices)]
    parity = cpu_cuda_inference_parity(cpu.final_fit.model, selected)
    assert parity["atol"] == 1e-6
    assert parity["rtol"] == 1e-5
    assert np.isfinite(parity["max_probability_difference"])
