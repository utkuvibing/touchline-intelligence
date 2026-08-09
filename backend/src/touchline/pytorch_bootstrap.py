"""Official process-start launcher for deterministic WP2.6 CPU and CUDA execution."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

REQUIRED_PROCESS_ENV = {
    "PYTHONHASHSEED": "0",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}
CUBLAS_WORKSPACE_CONFIG = ":4096:8"


class ProcessEnvironmentError(RuntimeError):
    """A conflicting inherited process setting would invalidate deterministic execution."""


def _pin(name: str, value: str) -> None:
    inherited = os.environ.get(name)
    if inherited is not None and inherited.strip() != value:
        raise ProcessEnvironmentError(
            f"{name} is {inherited!r}; WP2.6 requires {value!r} before compiled libraries import"
        )
    os.environ[name] = value


def pin_process_environment(*, cuda: bool) -> None:
    """Pin process variables before importing NumPy, scikit-learn or PyTorch."""
    for name, value in REQUIRED_PROCESS_ENV.items():
        _pin(name, value)
    if cuda:
        _pin("CUBLAS_WORKSPACE_CONFIG", CUBLAS_WORKSPACE_CONFIG)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(argv if argv is not None else sys.argv[1:])
    cuda = any(
        value == "cuda" and index > 0 and arguments[index - 1] == "--device"
        for index, value in enumerate(arguments)
    )
    pin_process_environment(cuda=cuda)
    from touchline.modeling.train_mlp import main as train_main

    return train_main(arguments)


if __name__ == "__main__":
    sys.exit(main())
