"""Regression contracts for the mutation runner's stale-bytecode invalidation.

The runner (``scripts/verify_tests_fail.py``) applies one deliberate break per protected
contract, runs the relevant tests, and restores the file. Part of keeping that restore real is
deleting the stale ``__pycache__`` entry a break's test run leaves behind: the run compiles the
mutated source and writes a pyc whose header records the source's integer-second mtime, so
restoring the original within the same second leaves that pyc looking fresh and a later import
silently runs the mutated code while the file shows the original.

Python cache files are named for the module plus an interpreter tag — ``splits.cpython-313.pyc``,
``splits.cpython-312.pyc``, ``splits.cpython-313.opt-1.pyc``. The invalidation must therefore be
keyed off the module stem (``splits``), never off the ``.py``-suffixed file name (``splits.py``),
which matches nothing. These tests pin that contract.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "verify_tests_fail.py"
_MODULE_NAME = "verify_tests_fail_under_test"


def _load_runner() -> Any:
    """Import the script as a plain module; it has no package imports or side effects.

    The module must be registered in ``sys.modules`` before execution: the script's own
    dataclass machinery resolves annotations through ``sys.modules[cls.__module__]``.
    """
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


def test_invalidate_bytecode_removes_every_interpreter_tag_for_the_module(
    tmp_path: Path,
) -> None:
    """The regression: pyc names carry the interpreter tag, not the ``.py`` suffix.

    The historical bug globbed ``f"{path.name}.*.pyc"`` — ``splits.py.*.pyc`` — which matches no
    real cache file, so the stale bytecode survived the restore. With the fix, every cache file
    whose name starts with the module stem is removed and unrelated modules are untouched.
    """
    invalidate = _load_runner()._invalidate_bytecode
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    pyc_312 = cache / "splits.cpython-312.pyc"
    pyc_313 = cache / "splits.cpython-313.pyc"
    pyc_optimized = cache / "splits.cpython-313.opt-1.pyc"
    unrelated = cache / "other.cpython-312.pyc"
    for path in (pyc_312, pyc_313, pyc_optimized, unrelated):
        path.write_bytes(b"\x00\x00\x00\x00")

    invalidate(tmp_path / "splits.py")

    assert not pyc_312.exists()
    assert not pyc_313.exists()
    assert not pyc_optimized.exists()
    assert unrelated.exists()


def test_invalidate_bytecode_tolerates_a_missing_cache_dir(tmp_path: Path) -> None:
    invalidate = _load_runner()._invalidate_bytecode
    invalidate(tmp_path / "splits.py")  # must not raise


def test_restore_exact_bytes_retries_a_transient_os_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _load_runner()
    target = tmp_path / "quality.py"
    original = b"original\r\n"
    target.write_bytes(b"mutated\r\n")
    real_write_bytes = Path.write_bytes
    calls = 0

    def fail_once(path: Path, data: bytes) -> int:
        nonlocal calls
        calls += 1
        if path == target and calls == 1:
            raise OSError(22, "Invalid argument", str(path))
        return real_write_bytes(path, data)

    monkeypatch.setattr(Path, "write_bytes", fail_once)
    runner._restore_exact_bytes(target, original, attempts=3, backoff_seconds=0.0)

    assert calls == 2
    assert target.read_bytes() == original


def test_restore_exact_bytes_fails_loudly_after_permanent_os_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _load_runner()
    target = tmp_path / "quality.py"
    original = b"original\r\n"
    mutated = b"mutated\r\n"
    target.write_bytes(mutated)

    def always_fail(path: Path, data: bytes) -> int:
        del data
        raise OSError(22, "Invalid argument", str(path))

    monkeypatch.setattr(Path, "write_bytes", always_fail)
    with pytest.raises(runner.MutationRestoreError, match="after 3 attempts"):
        runner._restore_exact_bytes(target, original, attempts=3, backoff_seconds=0.0)

    assert target.read_bytes() == mutated
