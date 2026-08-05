"""WP2.4 training entry point and protocol runner.

``python -m touchline.modeling.train --config <path>`` reads a JSON config, verifies the pinned
WP2.3 artifacts (byte-pin + canonical LF, §6), loads **development rows only** through the WP2.1
cohort query, and runs the locked protocol:

- three candidates (constant, geometry-only logistic, full logistic);
- the D5 ablation pair (full minus presence vs full, each with its own C);
- the D10 C-selection, the PLAN §4.1 pairwise replacement rule, and the D5 INCLUDE/EXCLUDE rule;
- a label-free presence report by development tournament and fold.

**The shipped artifact is the D5-selected candidate.** After D5 runs, exactly one candidate ships:
``full_logistic`` when D5 includes, ``full_minus_presence`` otherwise. The shipped candidate is
final-refitted with its own selected C over its exact feature-column subset using the
all-development scaler and locked vocabulary, and serialized as a **self-contained inference
bundle** (estimator +
scaler + vocabulary + column map + provenance) that scores raw ``ShotRow`` objects with no
re-fitting at inference time. The presence-inclusive full model is re-fitted **only diagnostically**
to supply the D5 final-refit coefficient signs; its coefficients are labelled diagnostic and never
called shipped-model coefficients.

`protocol_incumbent` (the PLAN §4.1 result) and `shipped_candidate` (what ships) are separate
concepts and separate fields.

It writes an experiment record (``config.json``, ``metrics.json``, ``notes.md``,
``artifact-manifest.json``) and one authoritative ``results.csv`` row for the experiment. It never
writes to the database: the connection is opened READ ONLY and the load is a
``SET TRANSACTION READ ONLY`` read.

All decisions are pre-registered in `docs/modeling/wp2_4-baselines-and-logistic-contract.md`; this
module only applies them. Nothing here reads holdout or calibration labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast

import numpy as np
import numpy.typing as npt
import psycopg

from touchline.modeling.artifact import ArtifactBundle, artifact_schema_version
from touchline.modeling.baselines import ConstantBaseline
from touchline.modeling.dataset import (
    load_development_cohort,
    parse_match_assignments,
    verify_assignments_csv,
    verify_cohort_sql,
    verify_development_anchor,
)
from touchline.modeling.logistic import (
    L2_C_GRID,
    LogisticModel,
    fit_logistic,
    select_regularization,
)
from touchline.modeling.metrics import (
    EvaluationResult,
    PerFoldMetrics,
    PooledOOFMetrics,
    ReliabilityEntry,
    canonical_metrics_json,
    evaluate_probability_scores,
)
from touchline.modeling.preprocessing import (
    CATEGORICAL_FIELDS,
    PRESENCE_SOURCE_FIELDS,
    RARE_MIN_DEV_ROWS,
    ShotRow,
    StandardScaler,
    Vocabulary,
    encode_rows,
    fit_scaler,
    fit_vocabulary,
)

ROOT = Path(__file__).resolve().parents[4]
CSV_PATH = ROOT / "data" / "model" / "wp2_3_match_assignments.csv"
COHORT_SQL_PATH = ROOT / "backend" / "sql" / "wp2_1" / "01_model_shot_cohort.sql"
DEFAULT_RESULTS_CSV = "experiments/results.csv"

#: Pre-registered D5/D11 floor: a reliability bin counts toward the calibration comparison only
#: when it holds at least this many pooled out-of-fold predictions.
D11_MIN_SUPPORT = 100

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int_]

REQUIRED_CONFIG_KEYS = frozenset(
    {
        "experiment_id",
        "out_dir",
        "artifacts_dir",
        "data_source_commit",
        "db_url_env",
        "assignments_sha256",
        "cohort_sql_sha256",
        "c_grid",
        "random_seed",
        "n_folds",
        "expected_shots",
        "expected_matches",
        "expected_fold_sizes",
        "bin_count",
    }
)


@dataclass(frozen=True)
class RunConfig:
    experiment_id: str
    out_dir: str
    artifacts_dir: str
    code_commit: str
    reproduction_commit: str
    data_source_commit: str
    input_config_path: str
    input_config_sha256: str
    uv_lock_sha256: str
    runtime_fingerprint: Mapping[str, object]
    require_clean_provenance: bool
    db_url_env: str
    assignments_sha256: str
    cohort_sql_sha256: str
    c_grid: tuple[float, ...]
    random_seed: int
    n_folds: int
    expected_shots: int
    expected_matches: int
    expected_fold_sizes: Mapping[int, int]
    bin_count: int
    results_csv: str


@dataclass(frozen=True)
class _FoldData:
    """One development fold's encoded matrices. The scaler was fitted on training rows only."""

    X_train: FloatArray
    X_val: FloatArray
    y_train: IntArray
    y_val: IntArray
    column_names: list[str]


class _RuleMetrics(TypedDict):
    """The fields the PLAN §4.1 replacement rule reads, structurally typed for the cast."""

    mean_log_loss: float
    sd_log_loss_ddof0: float
    max_abs_deviation_supported: float


class _CandidateReadOut(TypedDict):
    """The shipped-logistic fields the results.csv row reads, structurally typed for the cast."""

    mean_log_loss: float
    pooled_oof: PooledOOFMetrics


def _abs_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _record_path(value: str | Path) -> str:
    """Repository-relative POSIX path for committed records; absolute POSIX for non-repo paths.

    Committed experiment configuration and manifests must not carry drive letters, backslashes or
    machine-local absolute paths (blocking correction 5); temporary absolute paths (tests) stay
    absolute but always POSIX.
    """
    resolved = _abs_path(str(value)).resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _load_config(path: Path) -> RunConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"config {path} must be a JSON object")
    missing = REQUIRED_CONFIG_KEYS - set(payload)
    if missing:
        raise ValueError(f"config {path} is missing required keys: {sorted(missing)}")
    c_grid = tuple(float(c) for c in payload["c_grid"])
    if c_grid != L2_C_GRID:
        raise ValueError(
            f"C grid in config {c_grid} does not match the pre-registered D10 grid {L2_C_GRID}"
        )
    if int(payload["bin_count"]) != 5:
        raise ValueError("reliability bin count is locked at five (ADR 0004)")
    fold_sizes = {
        int(str(fold)): int(size) for fold, size in payload["expected_fold_sizes"].items()
    }
    return RunConfig(
        experiment_id=str(payload["experiment_id"]),
        out_dir=str(payload["out_dir"]),
        artifacts_dir=str(payload["artifacts_dir"]),
        # Provenance is derived at run time (see resolve_provenance); JSON-supplied values are not
        # trusted as the authoritative implementation revision (blocking correction 3).
        code_commit="unset",
        reproduction_commit="unset",
        data_source_commit=str(payload["data_source_commit"]),
        input_config_path=str(path),
        input_config_sha256="",
        uv_lock_sha256="",
        runtime_fingerprint={},
        require_clean_provenance=bool(payload.get("require_clean_provenance", False)),
        db_url_env=str(payload["db_url_env"]),
        assignments_sha256=str(payload["assignments_sha256"]),
        cohort_sql_sha256=str(payload["cohort_sql_sha256"]),
        c_grid=c_grid,
        random_seed=int(payload["random_seed"]),
        n_folds=int(payload["n_folds"]),
        expected_shots=int(payload["expected_shots"]),
        expected_matches=int(payload["expected_matches"]),
        expected_fold_sizes=fold_sizes,
        bin_count=int(payload["bin_count"]),
        results_csv=str(payload.get("results_csv", DEFAULT_RESULTS_CSV)),
    )


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


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(root: Path, *args: str) -> str:
    """Run git read-only inside ``root``; raises ProvenanceError on failure.

    Kept as a module function so tests can inject a deterministic revision seam.
    """
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise ProvenanceError(f"git {' '.join(args)} failed in {root}: {result.stderr.strip()}")
    return result.stdout.strip()


def _runtime_fingerprint() -> dict[str, object]:
    """A deterministic, sanitized description of the runtime that produced the evidence.

    No usernames, home-directory paths, executable paths, library file paths, temporary
    directories, environment secrets or DSNs are recorded; library ``filepath`` entries from the
    threadpool are deliberately excluded. Everything serializes deterministically (sorted keys).
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
        "threadpool_info": sanitized,
    }


def _require_clean_tracked_tree(root: Path) -> None:
    """Refuse to generate evidence while tracked files have uncommitted changes.

    Untracked and ignored files (e.g. ``IDEA.md`` or the git-ignored ``model.pkl``) are not
    tracked changes and are allowed; a modified tracked file makes the evidence unreproducible
    from any single commit.
    """
    status = _git(root, "status", "--porcelain")
    dirty = [line for line in status.splitlines() if line.strip() and not line.startswith("??")]
    if dirty:
        raise ProvenanceError(
            "refusing to generate evidence from a dirty tracked working tree: " + ", ".join(dirty)
        )


def resolve_provenance(
    config: RunConfig,
    code_commit_override: str | None = None,
) -> tuple[RunConfig, Provenance]:
    """Derive the authoritative reproduction identity and return the resolved run config.

    When ``require_clean_provenance`` is set (the committed real-run config), the code commit is
    taken from ``git rev-parse HEAD`` and the tracked working tree must be clean; a manual override
    is forbidden then. Otherwise (synthetic/unit runs) the caller may inject a deterministic
    ``code_commit_override`` seam.
    """
    runtime = _runtime_fingerprint()
    input_bytes = _abs_path(config.input_config_path).read_bytes()
    input_sha = _sha256_bytes(input_bytes)
    uv_sha = _sha256_bytes((ROOT / "uv.lock").read_bytes())
    if config.require_clean_provenance:
        if code_commit_override is not None:
            raise ProvenanceError(
                "--code-commit override is forbidden when require_clean_provenance is set"
            )
        code_commit = _git(ROOT, "rev-parse", "HEAD")
        _require_clean_tracked_tree(ROOT)
    else:
        code_commit = code_commit_override if code_commit_override else config.code_commit
    reproduction_commit = code_commit
    resolved = replace(
        config,
        code_commit=code_commit,
        reproduction_commit=reproduction_commit,
        input_config_sha256=input_sha,
        uv_lock_sha256=uv_sha,
        runtime_fingerprint=runtime,
    )
    provenance = Provenance(
        code_commit=code_commit,
        reproduction_commit=reproduction_commit,
        input_config_path=_record_path(config.input_config_path),
        input_config_sha256=input_sha,
        uv_lock_sha256=uv_sha,
        runtime_fingerprint=runtime,
        data_source_commit=config.data_source_commit,
    )
    return resolved, provenance


def _open_db(db_url: str, schema: str | None = None) -> psycopg.Connection:
    conn = psycopg.connect(db_url, connect_timeout=20)
    conn.read_only = True
    if schema:
        with conn.cursor() as cur:
            cur.execute(f'SET search_path TO "{schema}"')
    return conn


def build_vocabulary(rows: Sequence[ShotRow]) -> Vocabulary:
    """Label-free dev-wide vocabulary from development rows only (D8)."""
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        for field in CATEGORICAL_FIELDS:
            key = (field, str(getattr(row, field)))
            counts[key] = counts.get(key, 0) + 1
    return fit_vocabulary(counts, threshold=RARE_MIN_DEV_ROWS)


def _supported_deviations(
    reliability: Sequence[ReliabilityEntry], min_support: int
) -> tuple[float, int]:
    """Max |mean_prediction - observed_rate| over supported bins, and the supported-bin count."""
    deviations: list[float] = []
    for entry in reliability:
        if entry["count"] < min_support or entry["observed_rate"] is None:
            continue
        mean_prediction = entry["mean_prediction"]
        if mean_prediction is not None:
            deviations.append(abs(mean_prediction - entry["observed_rate"]))
    if not deviations:
        return 0.0, 0
    return float(max(deviations)), len(deviations)


def _evaluate_constant(rows: Sequence[ShotRow], n_folds: int) -> dict[str, object]:
    fold_pairs: list[tuple[IntArray, FloatArray]] = []
    for fold in range(n_folds):
        train = [r for r in rows if r.fold != fold]
        val = [r for r in rows if r.fold == fold]
        baseline = ConstantBaseline.fit([r.y for r in train])
        fold_pairs.append(
            (np.asarray([r.y for r in val], dtype=np.int_), baseline.predictions(len(val)))
        )
    return _finalize_metrics(evaluate_probability_scores(fold_pairs))


def _finalize_metrics(metrics: EvaluationResult) -> dict[str, object]:
    """Attach the D11-supported calibration summary the §4.1 rule reads."""
    max_deviation, supported_bins = _supported_deviations(metrics["reliability"], D11_MIN_SUPPORT)
    return {
        **metrics,
        "max_abs_deviation_supported": max_deviation,
        "supported_bins": supported_bins,
    }


def _selected_c(selected_folds: Sequence[_FoldData], config: RunConfig) -> float:
    fold_specs = [(fold.X_train, fold.X_val, fold.y_train, fold.y_val) for fold in selected_folds]
    best_c, _scored = select_regularization(
        fold_specs, config.c_grid, random_state=config.random_seed
    )
    return best_c


def _run_fold_logistic(
    selected_folds: Sequence[_FoldData],
    best_c: float,
    config: RunConfig,
    sign_columns: Sequence[str] = (),
) -> dict[str, object]:
    fold_pairs: list[tuple[IntArray, FloatArray]] = []
    sign_groups: dict[str, list[int]] = {name: [] for name in sign_columns}
    for fold in selected_folds:
        model = fit_logistic(fold.X_train, fold.y_train, best_c, random_state=config.random_seed)
        p_val = model.predict_proba(fold.X_val)
        fold_pairs.append((fold.y_val, p_val))
        for name in sign_columns:
            index = fold.column_names.index(name)
            sign_groups[name].append(_sign(float(model.estimator.coef_[0, index])))
    metrics = _finalize_metrics(evaluate_probability_scores(fold_pairs))
    metrics["best_c"] = best_c
    if sign_columns:
        metrics["raw_coefficient_sign_by_fold"] = dict(sign_groups)
    return metrics


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _presence_report(rows: Sequence[ShotRow], n_folds: int) -> dict[str, object]:
    per_field: dict[str, object] = {}
    for field in PRESENCE_SOURCE_FIELDS:
        present = [getattr(row, field) is True for row in rows]
        tournaments: dict[str, float] = {}
        groups: dict[tuple[int, int], list[bool]] = {}
        for row, flag in zip(rows, present, strict=True):
            groups.setdefault((row.competition_id, row.season_id), []).append(flag)
        for (competition, season), flags in groups.items():
            tournaments[f"({competition},{season})"] = float(np.mean(flags))
        fold_rates: dict[str, float] = {}
        for fold in range(n_folds):
            flags = [flag for row, flag in zip(rows, present, strict=True) if row.fold == fold]
            fold_rates[str(fold)] = float(np.mean(flags)) if flags else 0.0
        per_field[field] = {
            "presence_count": int(sum(present)),
            "development_rows": len(rows),
            "overall_rate": float(np.mean(present)),
            "by_tournament": tournaments,
            "by_fold": fold_rates,
        }
    return per_field


def _run_d5(
    full_metrics: Mapping[str, object],
    minus_metrics: Mapping[str, object],
    final_refit_signs: Mapping[str, int],
) -> dict[str, object]:
    full_per_fold = cast(Sequence[PerFoldMetrics], full_metrics["per_fold"])
    minus_per_fold = cast(Sequence[PerFoldMetrics], minus_metrics["per_fold"])
    # Delta is defined as: positive = full beats full-minus-presence.
    delta_ll = [
        float(a["log_loss"]) - float(b["log_loss"])
        for a, b in zip(minus_per_fold, full_per_fold, strict=True)
    ]
    delta_brier = [
        float(a["brier"]) - float(b["brier"])
        for a, b in zip(minus_per_fold, full_per_fold, strict=True)
    ]
    sign_groups = cast(Mapping[str, Sequence[int]], full_metrics["raw_coefficient_sign_by_fold"])
    # Condition 4: no sign flips — each indicator keeps the same raw fitted coefficient sign
    # across all five fold fits AND the final development refit.
    no_sign_flips = all(
        group and all(value == group[0] for value in group) and group[0] == final_refit_signs[name]
        for name, group in sign_groups.items()
    )
    include = (
        sum(1 for value in delta_ll if value > 0) >= 4
        and float(np.mean(delta_ll)) > 0
        and float(np.mean(delta_brier)) > 0
        and no_sign_flips
    )
    return {
        "include": include,
        "delta_log_loss_by_fold": delta_ll,
        "delta_brier_by_fold": delta_brier,
        "mean_delta_log_loss": float(np.mean(delta_ll)),
        "mean_delta_brier": float(np.mean(delta_brier)),
        "positive_log_loss_folds": sum(1 for value in delta_ll if value > 0),
        "positive_brier_folds": sum(1 for value in delta_brier if value > 0),
        "raw_coefficient_sign_by_fold": dict(sign_groups),
        "final_refit_sign": dict(final_refit_signs),
        "no_sign_flips": no_sign_flips,
    }


def _mean_brier(metrics: Mapping[str, object]) -> float:
    per_fold = cast(Sequence[PerFoldMetrics], metrics["per_fold"])
    return float(np.mean([entry["brier"] for entry in per_fold]))


def _replacement_rule(incumbent: Mapping[str, object], candidate: Mapping[str, object]) -> bool:
    incumbent_r = cast(_RuleMetrics, incumbent)
    candidate_r = cast(_RuleMetrics, candidate)
    return (
        candidate_r["mean_log_loss"]
        < incumbent_r["mean_log_loss"] - incumbent_r["sd_log_loss_ddof0"]
        and _mean_brier(candidate) <= _mean_brier(incumbent)
        and candidate_r["max_abs_deviation_supported"] <= incumbent_r["max_abs_deviation_supported"]
        and candidate_r["sd_log_loss_ddof0"] <= incumbent_r["sd_log_loss_ddof0"]
    )


def _run_replacements(
    candidates: Mapping[str, Mapping[str, object]],
    shipped_key: str,
) -> tuple[dict[str, object], str]:
    """Plan §4.1 applied to the D5-selected candidate: constant -> geometry -> shipped candidate.

    ``protocol_incumbent`` is the §4.1 result and is deliberately a separate concept from
    ``shipped_candidate``: the rule can name the constant (its constructed near-zero calibration
    deviation makes condition 3 unachievable) while the shipped model is a real predictor.
    """
    geometry_beats_constant = _replacement_rule(
        candidates["constant"], candidates["geometry_logistic"]
    )
    incumbent = "constant" if not geometry_beats_constant else "geometry_logistic"
    shipped_beats_incumbent = _replacement_rule(candidates[incumbent], candidates[shipped_key])
    if shipped_beats_incumbent:
        incumbent = shipped_key
    return {
        "geometry_beats_constant": geometry_beats_constant,
        "shipped_beats_incumbent": shipped_beats_incumbent,
        "protocol_incumbent": incumbent,
    }, incumbent


def _build_folds(
    rows: Sequence[ShotRow],
    vocabulary: Vocabulary,
    n_folds: int,
) -> list[_FoldData]:
    """Per-fold encoded matrices; the scaler is fitted on **training rows only** per fold."""
    selected_folds: list[_FoldData] = []
    for fold in range(n_folds):
        train = [r for r in rows if r.fold != fold]
        val = [r for r in rows if r.fold == fold]
        scaler = fit_scaler(train)
        X_train, column_names = encode_rows(train, vocabulary, scaler)
        X_val, _ = encode_rows(val, vocabulary, scaler)
        selected_folds.append(
            _FoldData(
                X_train=X_train,
                X_val=X_val,
                y_train=np.asarray([r.y for r in train], dtype=np.int_),
                y_val=np.asarray([r.y for r in val], dtype=np.int_),
                column_names=column_names,
            )
        )
    return selected_folds


def _refit_columns(
    rows: Sequence[ShotRow],
    vocabulary: Vocabulary,
    scaler: StandardScaler,
    all_columns: Sequence[str],
    indices: Sequence[int],
    best_c: float,
    random_seed: int,
) -> tuple[LogisticModel, list[dict[str, object]], dict[str, object]]:
    """Refit over a specified column subset for one full development run.

    Used for both the D5 diagnostic presence-inclusive refit and the final shipped-candidate refit;
    the subset, C and scaler are the caller's choice and are recorded in the returned metadata.
    """
    rows_list = list(rows)
    full, _ = encode_rows(rows_list, vocabulary, scaler)
    subset = full[:, list(indices)]
    y = np.asarray([row.y for row in rows_list], dtype=np.int_)
    model = fit_logistic(subset, y, best_c, random_state=random_seed)
    coef = model.estimator.coef_[0]
    table: list[dict[str, object]] = []
    for position, index in enumerate(indices):
        name = all_columns[index]
        value = float(coef[position])
        table.append(
            {
                "feature": name,
                "standardized_coefficient": value,
                "odds_ratio": float(np.exp(value)),
                "presence_indicator": name.endswith("_presence"),
            }
        )
    return (
        model,
        table,
        {
            "best_c": best_c,
            "intercept": float(model.estimator.intercept_[0]),
            "n_training_rows": len(rows_list),
            "feature_columns": [all_columns[index] for index in indices],
        },
    )


def run_protocol(
    rows: Sequence[ShotRow],
    config: RunConfig,
) -> tuple[dict[str, object], ArtifactBundle]:
    """Run the locked protocol; returns (metrics, shipped inference bundle)."""
    rows_list = list(rows)
    n_folds = config.n_folds
    vocabulary = build_vocabulary(rows_list)
    all_columns = vocabulary.column_names()
    scaler_all = fit_scaler(rows_list)

    selected_folds = _build_folds(rows_list, vocabulary, n_folds)

    def restrict(columns_to_keep: list[int]) -> list[_FoldData]:
        return [
            _FoldData(
                X_train=fold.X_train[:, columns_to_keep],
                X_val=fold.X_val[:, columns_to_keep],
                y_train=fold.y_train,
                y_val=fold.y_val,
                column_names=[fold.column_names[i] for i in columns_to_keep],
            )
            for fold in selected_folds
        ]

    full_columns = list(range(len(all_columns)))
    geometry_columns = [0, 1]
    presence_columns = [2, 3]  # first_time_presence, under_pressure_presence
    minus_columns = [i for i in full_columns if i not in presence_columns]

    candidates: dict[str, Mapping[str, object]] = {}
    candidates["constant"] = _evaluate_constant(rows_list, n_folds)

    geometry_folds = restrict(geometry_columns)
    candidates["geometry_logistic"] = _run_fold_logistic(
        geometry_folds, _selected_c(geometry_folds, config), config
    )

    full_folds = restrict(full_columns)
    presence_names = [f"{field}_presence" for field in PRESENCE_SOURCE_FIELDS]
    candidates["full_logistic"] = _run_fold_logistic(
        full_folds, _selected_c(full_folds, config), config, sign_columns=presence_names
    )

    minus_folds = restrict(minus_columns)
    candidates["full_minus_presence"] = _run_fold_logistic(
        minus_folds, _selected_c(minus_folds, config), config
    )
    full_best_c = cast(float, candidates["full_logistic"]["best_c"])

    # D5's condition 4 needs the presence coefficients of a full development refit. That refit is
    # produced here only to read those signs; it is diagnostic and its coefficients are never the
    # shipped model's (blocking correction 1).
    _diag_model, diag_coefficients, diag_refit = _refit_columns(
        rows_list,
        vocabulary,
        scaler_all,
        all_columns,
        full_columns,
        full_best_c,
        config.random_seed,
    )
    d5 = _run_d5(
        candidates["full_logistic"],
        candidates["full_minus_presence"],
        {
            str(entry["feature"]): _sign(cast(float, entry["standardized_coefficient"]))
            for entry in diag_coefficients
            if str(entry["feature"]).endswith("_presence")
        },
    )

    # Select exactly one shipped candidate (pre-registered rule; never tuned).
    shipped = "full_logistic" if d5["include"] else "full_minus_presence"
    shipped_indices = full_columns if d5["include"] else minus_columns
    shipped_best_c = cast(float, candidates[shipped]["best_c"])

    # Final refit of the D5-selected candidate: its own C, its exact column subset, the
    # all-development scaler, the locked development vocabulary (blocking corrections 1, 2).
    _ship_model, shipped_coefficients, shipped_refit = _refit_columns(
        rows_list,
        vocabulary,
        scaler_all,
        all_columns,
        shipped_indices,
        shipped_best_c,
        config.random_seed,
    )
    bundle = ArtifactBundle(
        schema_version=artifact_schema_version,
        experiment_id=config.experiment_id,
        shipped_candidate=shipped,
        best_c=shipped_best_c,
        code_commit=config.code_commit,
        reproduction_commit=config.reproduction_commit,
        data_source_commit=config.data_source_commit,
        cohort_sql_sha256=config.cohort_sql_sha256,
        assignments_sha256=config.assignments_sha256,
        input_config_sha256=config.input_config_sha256,
        uv_lock_sha256=config.uv_lock_sha256,
        estimator=_ship_model.estimator,
        scaler=scaler_all,
        vocabulary=vocabulary,
        all_columns=tuple(all_columns),
        selected_columns=tuple(all_columns[index] for index in shipped_indices),
        selected_indices=tuple(int(index) for index in shipped_indices),
        reference_levels=dict(vocabulary.reference),
        rare_mapping={field: tuple(levels) for field, levels in vocabulary.rare_members.items()},
    )

    replacement, protocol_incumbent = _run_replacements(candidates, shipped)

    diagnostics: dict[str, object] = {
        "note": (
            "the presence-inclusive full development refit is diagnostic only (D5 sign record); "
            "its coefficients are NOT the shipped model's"
        ),
        "rejected_candidate": "full_logistic" if shipped != "full_logistic" else None,
        "presence_inclusive_full_refit": {
            "best_c": full_best_c,
            "intercept": diag_refit["intercept"],
            "feature_columns": diag_refit["feature_columns"],
            "coefficients": diag_coefficients,
        },
    }

    metrics: dict[str, object] = {
        "experiment_id": config.experiment_id,
        "code_commit": config.code_commit,
        "reproduction_commit": config.reproduction_commit,
        "data_source_commit": config.data_source_commit,
        "input_config_path": _record_path(config.input_config_path),
        "input_config_sha256": config.input_config_sha256,
        "uv_lock_sha256": config.uv_lock_sha256,
        "runtime_fingerprint": config.runtime_fingerprint,
        "cohort_sql_sha256": config.cohort_sql_sha256,
        "assignments_sha256": config.assignments_sha256,
        "n_rows": len(rows_list),
        "n_matches": len({row.match_id for row in rows_list}),
        "c_grid": list(config.c_grid),
        "random_seed": config.random_seed,
        "bin_count": config.bin_count,
        "d11_min_support": D11_MIN_SUPPORT,
        "vocabulary": vocabulary.as_dict(),
        "candidates": candidates,
        "d5": d5,
        "d5_include": d5["include"],
        "protocol_incumbent": protocol_incumbent,
        "shipped_candidate": shipped,
        "shipped_feature_set": (
            "geometry+categoricals+presence-indicators"
            if d5["include"]
            else "geometry+categoricals"
        ),
        "shipped_best_c": shipped_best_c,
        "shipped_feature_columns": [all_columns[index] for index in shipped_indices],
        "replacement_rule": replacement,
        "presence_report": _presence_report(rows_list, n_folds),
        "coefficients": shipped_coefficients,
        "shipped_dev_refit": shipped_refit,
        "diagnostics": diagnostics,
        "model_pickle_sha256": _pickle_sha(bundle),
    }
    return metrics, bundle


def _pickle_sha(model: object) -> str:
    return hashlib.sha256(pickle.dumps(model, protocol=5)).hexdigest()


def write_experiment(
    metrics: Mapping[str, object], bundle: ArtifactBundle, config: RunConfig
) -> list[Path]:
    """Write the experiment record for the **shipped candidate** and one authoritative row."""
    out = _abs_path(config.out_dir)
    art = _abs_path(config.artifacts_dir)
    out.mkdir(parents=True, exist_ok=True)
    art.mkdir(parents=True, exist_ok=True)

    shipped_key = cast(str, metrics["shipped_candidate"])
    candidates = cast(Mapping[str, object], metrics["candidates"])
    shipped_metrics = cast(_CandidateReadOut, candidates[shipped_key])

    pickle_bytes = pickle.dumps(bundle, protocol=5)
    bundle_hash = hashlib.sha256(pickle_bytes).hexdigest()
    recorded_hash = cast(str, metrics["model_pickle_sha256"])
    if bundle_hash != recorded_hash:
        raise AssertionError(
            f"bundle pickle SHA {bundle_hash} != recorded {recorded_hash}; records must agree"
        )

    (out / "metrics.json").write_bytes(canonical_metrics_json(metrics))

    config_dict = {
        "experiment_id": config.experiment_id,
        "out_dir": _record_path(config.out_dir),
        "artifacts_dir": _record_path(config.artifacts_dir),
        "code_commit": config.code_commit,
        "reproduction_commit": config.reproduction_commit,
        "data_source_commit": config.data_source_commit,
        "input_config_path": _record_path(config.input_config_path),
        "input_config_sha256": config.input_config_sha256,
        "uv_lock_sha256": config.uv_lock_sha256,
        "runtime_fingerprint": config.runtime_fingerprint,
        "db_url_env": config.db_url_env,
        "assignments_sha256": config.assignments_sha256,
        "cohort_sql_sha256": config.cohort_sql_sha256,
        "c_grid": list(config.c_grid),
        "random_seed": config.random_seed,
        "n_folds": config.n_folds,
        "expected_shots": config.expected_shots,
        "expected_matches": config.expected_matches,
        "expected_fold_sizes": dict(config.expected_fold_sizes),
        "bin_count": config.bin_count,
        "results_csv": _record_path(config.results_csv),
        "shipped_candidate": shipped_key,
        "shipped_feature_set": metrics["shipped_feature_set"],
        "shipped_best_c": metrics["shipped_best_c"],
        "shipped_feature_columns": list(cast(list[object], metrics["shipped_feature_columns"])),
        "d5_include": metrics["d5_include"],
    }
    (out / "config.json").write_bytes(canonical_metrics_json(config_dict))

    (out / "notes.md").write_text(_notes_template(config), encoding="utf-8")

    pickle_path = art / "model.pkl"
    pickle_path.write_bytes(pickle_bytes)
    input_cfg_posix = _record_path(config.input_config_path)
    artifact_manifest = {
        "experiment_id": config.experiment_id,
        "code_commit": config.code_commit,
        "reproduction_commit": config.reproduction_commit,
        "data_source_commit": config.data_source_commit,
        "input_config_path": input_cfg_posix,
        "input_config_sha256": config.input_config_sha256,
        "uv_lock_sha256": config.uv_lock_sha256,
        "runtime_fingerprint": config.runtime_fingerprint,
        "artifact_schema_version": artifact_schema_version,
        "shipped_candidate": shipped_key,
        "shipped_feature_set": metrics["shipped_feature_set"],
        "shipped_best_c": metrics["shipped_best_c"],
        "shipped_feature_columns": list(cast(list[object], metrics["shipped_feature_columns"])),
        "d5_include": metrics["d5_include"],
        "model_pickle_path": _record_path(pickle_path),
        "model_pickle_sha256": bundle_hash,
        "recreation": {
            "checkout": f"git checkout {config.reproduction_commit}",
            "sync": "uv sync --locked",
            "database": (
                "set TOUCHLINE_FULL_COHORT_DB_URL to the local ingested four-tournament database"
            ),
            "run": f"uv run python -m touchline.modeling.train --config {input_cfg_posix}",
        },
        "recreation_command": (
            f"uv run python -m touchline.modeling.train --config {input_cfg_posix}"
        ),
        "coefficients_json": _record_path(out / "metrics.json"),
    }
    (out / "artifact-manifest.json").write_bytes(canonical_metrics_json(artifact_manifest))

    results_row = {
        "experiment_id": config.experiment_id,
        "date_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "code_commit": config.code_commit,
        "reproduction_commit": config.reproduction_commit,
        "data_source_commit": config.data_source_commit,
        "dataset_id": "wp2_3_split_lock",
        "query_hash": config.cohort_sql_sha256,
        "input_config_sha256": config.input_config_sha256,
        "uv_lock_sha256": config.uv_lock_sha256,
        "shipped_feature_set": metrics["shipped_feature_set"],
        "split_strategy": "wp2_3_tournament_split",
        "model": "regularized-logistic",
        "seed": config.random_seed,
        "primary_metric": "mean_log_loss",
        "primary_value": shipped_metrics["mean_log_loss"],
        "brier": shipped_metrics["pooled_oof"]["brier"],
        "log_loss": shipped_metrics["pooled_oof"]["log_loss"],
        "protocol_incumbent": metrics["protocol_incumbent"],
        "shipped_candidate": shipped_key,
        "d5_include": metrics["d5_include"],
        "shipped_best_c": metrics["shipped_best_c"],
        "model_pickle_sha256": bundle_hash,
        "calibration_summary": "five-bin equal-width; D11 support applied",
        "status": "complete",
        "notes_path": _record_path(out / "notes.md"),
    }
    _replace_results_csv(config.results_csv, results_row)
    return [
        out / "metrics.json",
        out / "config.json",
        out / "notes.md",
        out / "artifact-manifest.json",
        pickle_path,
    ]


RESULTS_CSV_HEADER = (
    "experiment_id,date_utc,code_commit,reproduction_commit,data_source_commit,dataset_id,"
    "query_hash,input_config_sha256,uv_lock_sha256,shipped_feature_set,split_strategy,model,seed,"
    "primary_metric,primary_value,brier,log_loss,protocol_incumbent,shipped_candidate,d5_include,"
    "shipped_best_c,model_pickle_sha256,calibration_summary,status,notes_path"
)


def _read_results_rows(path: Path) -> list[list[str]]:
    if not path.exists() or path.read_text(encoding="utf-8").strip() == "":
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.split(",") for line in lines[1:] if line.strip()]


def _replace_results_csv(path: str, row: Mapping[str, object]) -> None:
    """Write one authoritative row per experiment, preserving prior experiments (append-only).

    The review's blocking correction 3 requires the duplicate local rows for this branch-local
    experiment to collapse to exactly one authoritative row, while future published runs remain
    append-only.
    """
    header = RESULTS_CSV_HEADER
    keys = header.split(",")
    new_row = [str(row[key]) for key in keys]
    resolved = _abs_path(path)
    prior = [r for r in _read_results_rows(resolved) if not r or r[0] != str(row["experiment_id"])]
    with resolved.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(header + "\n")
        for existing in prior:
            handle.write(",".join(existing) + "\n")
        handle.write(",".join(new_row) + "\n")


def _notes_template(config: RunConfig) -> str:
    return (
        "# WP2.4 experiment run\n\n"
        f"Experiment: {config.experiment_id}\n\n"
        f"Code commit: {config.code_commit}\n"
        f"Reproduction commit: {config.reproduction_commit}\n"
        f"Input config: {config.input_config_path}\n\n"
        "Hypothesis: a regularized logistic regression over the locked feature set beats both "
        "baselines under PLAN §4.1; presence indicators are admissible only if the D5 protocol "
        "passes. The shipped artifact is the D5-selected candidate, never the rejected one.\n\n"
        "See metrics.json for the measured protocol result and the shipped candidate; see "
        "docs/modeling/wp2_4-baselines-and-logistic-contract.md for the pre-registered decisions.\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="touchline.modeling.train")
    parser.add_argument("--config", required=True, help="path to the run config JSON")
    parser.add_argument(
        "--assignments-csv",
        default=str(CSV_PATH),
        help="override the pinned assignment CSV (integration-test seam only; default is the lock)",
    )
    parser.add_argument(
        "--cohort-sql",
        default=str(COHORT_SQL_PATH),
        help="override the pinned cohort SQL (integration-test seam only; default is the lock)",
    )
    parser.add_argument(
        "--code-commit",
        default=None,
        help=(
            "deterministic git-revision seam for synthetic/unit runs; forbidden when "
            "require_clean_provenance is set (the real run derives HEAD itself)"
        ),
    )
    args = parser.parse_args(argv)

    config = _load_config(Path(args.config))
    if config.require_clean_provenance and args.code_commit is not None:
        print(
            "--code-commit override is forbidden when require_clean_provenance is set",
            file=sys.stderr,
        )
        return 1
    config, provenance = resolve_provenance(config, code_commit_override=args.code_commit)
    db_url_source = os.environ.get(config.db_url_env) or os.environ.get("TOUCHLINE_DB_URL")
    if not db_url_source:
        print(
            f"Refusing to run: neither {config.db_url_env} nor TOUCHLINE_DB_URL is set.",
            file=sys.stderr,
        )
        return 1

    assignments_bytes = Path(args.assignments_csv).read_bytes()
    verify_assignments_csv(assignments_bytes, config.assignments_sha256)
    assignments = parse_match_assignments(assignments_bytes.decode("utf-8"))
    cohort_sql = verify_cohort_sql(Path(args.cohort_sql).read_bytes(), config.cohort_sql_sha256)

    schema_override = os.environ.get("TOUCHLINE_TRAIN_SCHEMA")
    conn = _open_db(db_url_source, schema_override)
    try:
        rows = load_development_cohort(conn, cohort_sql, assignments)
    finally:
        conn.close()
    verify_development_anchor(
        rows,
        expected_shots=config.expected_shots,
        expected_matches=config.expected_matches,
        expected_fold_sizes=config.expected_fold_sizes,
    )

    metrics, bundle = run_protocol(rows, config)
    write_experiment(metrics, bundle, config)
    print(f"Wrote experiment record: {_record_path(config.out_dir)}")
    print(
        f"Shipped: {metrics['shipped_candidate']} | D5 include: {metrics['d5_include']} "
        f"| protocol incumbent: {metrics['protocol_incumbent']}"
    )
    print(f"code_commit: {provenance.code_commit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
