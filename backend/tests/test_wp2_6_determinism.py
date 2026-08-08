"""Process-start, device and pre-registration gates for WP2.6."""

from __future__ import annotations

import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest
import torch

from touchline.modeling.mlp import configure_deterministic_runtime
from touchline.modeling.train_mlp import (
    MlpConfigError,
    PreRegistrationError,
    check_pre_registration,
    load_config,
    resolve_device,
)
from touchline.pytorch_bootstrap import REQUIRED_PROCESS_ENV, pin_process_environment

ROOT = Path(__file__).resolve().parents[2]


def test_bootstrap_pins_every_process_start_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in REQUIRED_PROCESS_ENV:
        monkeypatch.delenv(name, raising=False)
    pin_process_environment(cuda=True)
    assert os.environ["PYTHONHASHSEED"] == "0"
    assert os.environ["OMP_NUM_THREADS"] == "1"
    assert os.environ["MKL_NUM_THREADS"] == "1"
    assert os.environ["CUBLAS_WORKSPACE_CONFIG"] == ":4096:8"


def test_device_resolution_never_silently_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    assert resolve_device("cpu") == torch.device("cpu")
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with pytest.raises(RuntimeError, match="CUDA was requested"):
        resolve_device("cuda")
    with pytest.raises(ValueError, match="device must be"):
        resolve_device("auto")


def test_proposed_adr_blocks_before_any_training_or_data_access() -> None:
    with pytest.raises(PreRegistrationError, match="not accepted"):
        check_pre_registration(ROOT / "docs/adr/0012-wp2-6-bounded-pytorch-mlp-lifecycle.md")


def test_committed_config_is_the_exact_pre_registered_contract(tmp_path: Path) -> None:
    config_path = ROOT / "experiments/run-configs/wp2_6-pytorch-mlp.json"
    config = load_config(config_path)
    assert config.random_seed == 0
    assert config.n_folds == 5
    assert config.expected_shots == 2872
    payload = config_path.read_text(encoding="utf-8").replace('"epochs": 200', '"epochs": 201')
    mutated = tmp_path / "mutated.json"
    mutated.write_text(payload, encoding="utf-8")
    with pytest.raises(MlpConfigError, match="training constants"):
        load_config(mutated)


def test_fresh_bootstrap_process_imports_torch_only_after_environment_pin() -> None:
    probe = (
        "import os,sys; from touchline.pytorch_bootstrap import pin_process_environment; "
        "assert 'torch' not in sys.modules; pin_process_environment(cuda=False); import torch; "
        "assert os.environ['PYTHONHASHSEED']=='0'; assert os.environ['OMP_NUM_THREADS']=='1'; "
        "assert os.environ['MKL_NUM_THREADS']=='1'"
    )
    result = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, check=False)
    assert result.returncode == 0


def test_canonical_cpu_lifecycle_reproduces_in_two_fresh_processes() -> None:
    environment = dict(os.environ)
    environment.update({"PYTHONHASHSEED": "0", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"})
    environment["PYTHONPATH"] = str(ROOT / "backend/tests")
    first = subprocess.run(
        [sys.executable, "-m", "support.wp26_cpu_probe"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    second = subprocess.run(
        [sys.executable, "-m", "support.wp26_cpu_probe"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first.stdout == second.stdout


def test_deterministic_algorithms_are_hard_errors_in_the_runtime_policy() -> None:
    source = inspect.getsource(configure_deterministic_runtime)
    assert "torch.use_deterministic_algorithms(True, warn_only=False)" in source
