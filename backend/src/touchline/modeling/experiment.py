"""Provenance derivation and experiment-record IO, shared by every training entry point.

This module answers one question for any candidate family: *what exactly produced this evidence, and
can another machine reproduce it?* It derives the runnable-reproduction identity (code commit, input
config digest, ``uv.lock`` digest, sanitized runtime fingerprint), enforces the clean-tracked-tree
rule, writes the append-only results index, and provides the path-recording helpers that keep
committed records portable.

It is deliberately **model-agnostic and config-agnostic**. It never imports a training module, and
it never names a concrete run-configuration class: everything it needs from a config is declared by
the :class:`ConfigLike` protocol, which both WP2.4's ``RunConfig`` and WP2.5's ``BoostingRunConfig``
satisfy structurally. ``resolve_provenance`` therefore returns a :class:`Provenance` only; each
entry point applies its own ``dataclasses.replace``.

Extracted from ``touchline.modeling.train`` without behaviour change.
"""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast, runtime_checkable

import psycopg

ROOT = Path(__file__).resolve().parents[4]

DEFAULT_RESULTS_CSV = "experiments/results.csv"

RESULTS_CSV_HEADER = (
    "experiment_id,date_utc,code_commit,reproduction_commit,data_source_commit,dataset_id,"
    "query_hash,input_config_sha256,uv_lock_sha256,shipped_feature_set,split_strategy,model,seed,"
    "primary_metric,primary_value,brier,log_loss,protocol_incumbent,shipped_candidate,d5_include,"
    "shipped_best_c,model_pickle_sha256,calibration_summary,status,notes_path"
)


@runtime_checkable
class ConfigLike(Protocol):
    """The only configuration surface this module reads.

    Declared as read-only properties so a frozen dataclass satisfies it without any inheritance,
    which is what keeps this module free of a dependency on either training entry point.
    """

    @property
    def code_commit(self) -> str: ...

    @property
    def data_source_commit(self) -> str: ...

    @property
    def input_config_path(self) -> str: ...

    @property
    def require_clean_provenance(self) -> bool: ...


class ProvenanceError(RuntimeError):
    """Evidence-generation provenance is missing, dirty or unverifiable."""


@dataclass(frozen=True)
class Provenance:
    """The runnable-reproduction identity recorded into every machine record (blocking 3)."""

    code_commit: str
    reproduction_commit: str
    input_config_path: str
    input_config_sha256: str
    uv_lock_sha256: str
    runtime_fingerprint: Mapping[str, object]
    data_source_commit: str

    def as_dict(self) -> dict[str, object]:
        return {
            "code_commit": self.code_commit,
            "reproduction_commit": self.reproduction_commit,
            "input_config_path": self.input_config_path,
            "input_config_sha256": self.input_config_sha256,
            "uv_lock_sha256": self.uv_lock_sha256,
            "runtime_fingerprint": self.runtime_fingerprint,
            "data_source_commit": self.data_source_commit,
        }


def abs_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def record_path(value: str | Path) -> str:
    """Repository-relative POSIX path for committed records; absolute POSIX for non-repo paths.

    Committed experiment configuration and manifests must not carry drive letters, backslashes or
    machine-local absolute paths (blocking correction 5); temporary absolute paths (tests) stay
    absolute but always POSIX.
    """
    resolved = abs_path(str(value)).resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pickle_sha(model: object) -> str:
    return hashlib.sha256(pickle.dumps(model, protocol=5)).hexdigest()


def git(root: Path, *args: str) -> str:
    """Run git read-only inside ``root``; raises ProvenanceError on failure.

    Kept as a module function so tests can inject a deterministic revision seam.
    """
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise ProvenanceError(f"git {' '.join(args)} failed in {root}: {result.stderr.strip()}")
    return result.stdout.strip()


def runtime_fingerprint() -> dict[str, object]:
    """A deterministic, sanitized description of the runtime that produced the evidence.

    No usernames, home-directory paths, executable paths, library file paths, temporary
    directories, environment secrets or DSNs are recorded; library ``filepath`` entries from the
    threadpool are deliberately excluded. Everything serializes deterministically (sorted keys).

    ``omp_num_threads`` and ``threadpool_num_threads`` record the D20 thread pin from both sides:
    the environment the process was started under, and the thread count the loaded runtimes
    actually report. Recording only the first would not prove the pin took effect; recording only
    the second would not show it was pinned rather than coincidental.
    """
    import platform

    import numpy as np
    import scipy  # type: ignore[import-untyped]
    import sklearn  # type: ignore[import-untyped]
    import threadpoolctl  # type: ignore[import-untyped]

    sanitized: list[dict[str, object]] = []
    for entry in threadpoolctl.threadpool_info():
        safe = {key: value for key, value in dict(entry).items() if key != "filepath"}
        sanitized.append(safe)
    sanitized.sort(key=lambda item: json.dumps(item, sort_keys=True))
    thread_counts = sorted({int(cast(int, entry["num_threads"])) for entry in sanitized})
    return {
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "os": platform.system(),
        "os_release": platform.release(),
        "machine": platform.machine(),
        "numpy_version": np.__version__,
        "scipy_version": scipy.__version__,
        "scikit_learn_version": sklearn.__version__,
        "threadpoolctl_version": threadpoolctl.__version__,
        "omp_num_threads": os.environ.get("OMP_NUM_THREADS"),
        "threadpool_num_threads": thread_counts,
        "threadpool_info": sanitized,
    }


def require_clean_tracked_tree(root: Path) -> None:
    """Refuse to generate evidence while tracked files have uncommitted changes.

    Untracked and ignored files (e.g. ``IDEA.md`` or the git-ignored ``model.pkl``) are not
    tracked changes and are allowed; a modified tracked file makes the evidence unreproducible
    from any single commit.
    """
    status = git(root, "status", "--porcelain")
    dirty = [line for line in status.splitlines() if line.strip() and not line.startswith("??")]
    if dirty:
        raise ProvenanceError(
            "refusing to generate evidence from a dirty tracked working tree: " + ", ".join(dirty)
        )


def resolve_provenance(
    config: ConfigLike,
    code_commit_override: str | None = None,
) -> Provenance:
    """Derive the authoritative reproduction identity for this run.

    When ``require_clean_provenance`` is set (the committed real-run config), the code commit is
    taken from ``git rev-parse HEAD`` and the tracked working tree must be clean; a manual override
    is forbidden then. Otherwise (synthetic/unit runs) the caller may inject a deterministic
    ``code_commit_override`` seam.

    The caller folds the returned identity back into its own run config; this module does not name
    a concrete config class.
    """
    runtime = runtime_fingerprint()
    input_bytes = abs_path(config.input_config_path).read_bytes()
    input_sha = sha256_bytes(input_bytes)
    uv_sha = sha256_bytes((ROOT / "uv.lock").read_bytes())
    if config.require_clean_provenance:
        if code_commit_override is not None:
            raise ProvenanceError(
                "--code-commit override is forbidden when require_clean_provenance is set"
            )
        code_commit = git(ROOT, "rev-parse", "HEAD")
        require_clean_tracked_tree(ROOT)
    else:
        code_commit = code_commit_override if code_commit_override else config.code_commit
    reproduction_commit = code_commit
    return Provenance(
        code_commit=code_commit,
        reproduction_commit=reproduction_commit,
        input_config_path=record_path(config.input_config_path),
        input_config_sha256=input_sha,
        uv_lock_sha256=uv_sha,
        runtime_fingerprint=runtime,
        data_source_commit=config.data_source_commit,
    )


def open_db(db_url: str, schema: str | None = None) -> psycopg.Connection:
    conn = psycopg.connect(db_url, connect_timeout=20)
    conn.read_only = True
    if schema:
        with conn.cursor() as cur:
            cur.execute(f'SET search_path TO "{schema}"')
    return conn


def read_results_rows(path: Path) -> list[list[str]]:
    if not path.exists() or path.read_text(encoding="utf-8").strip() == "":
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.split(",") for line in lines[1:] if line.strip()]


def replace_results_csv(path: str, row: Mapping[str, object]) -> None:
    """Write one authoritative row per experiment, preserving prior experiments (append-only).

    The review's blocking correction 3 requires the duplicate local rows for this branch-local
    experiment to collapse to exactly one authoritative row, while future published runs remain
    append-only.

    The header is fixed. Prior rows are re-emitted positionally, so widening
    ``RESULTS_CSV_HEADER`` would silently misalign every committed row that predates the change;
    that is why WP2.5 writes into the existing columns instead of adding new ones.
    """
    header = RESULTS_CSV_HEADER
    keys = header.split(",")
    new_row = [str(row[key]) for key in keys]
    resolved = abs_path(path)
    prior = [r for r in read_results_rows(resolved) if not r or r[0] != str(row["experiment_id"])]
    with resolved.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(header + "\n")
        for existing in prior:
            handle.write(",".join(existing) + "\n")
        handle.write(",".join(new_row) + "\n")
