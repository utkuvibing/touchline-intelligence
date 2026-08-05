"""WP2.4 training entry point and protocol runner.

``python -m touchline.modeling.train --config <path>`` reads a JSON config, verifies the pinned
WP2.3 artifacts (byte-pin + canonical LF, §6), loads **development rows only** through the WP2.1
cohort query, and runs the locked protocol:

- three candidates (constant, geometry-only logistic, full logistic);
- the D5 ablation pair (full minus presence vs full, each with its own C);
- the D10 C-selection, the PLAN §4.1 pairwise replacement rule, and the D5 INCLUDE/EXCLUDE rule;
- a label-free presence report by development tournament and fold.

It writes an experiment record (``config.json``, ``metrics.json``, ``notes.md``,
``artifact-manifest.json``) and appends one ``results.csv`` row. It never writes to the database:
the connection is opened READ ONLY and the load is a ``SET TRANSACTION READ ONLY`` read.

All decisions are pre-registered in `docs/modeling/wp2_4-baselines-and-logistic-contract.md`; this
module only applies them. Nothing here reads holdout or calibration labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast

import numpy as np
import numpy.typing as npt
import psycopg

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
    Vocabulary,
    encode_rows,
    fit_scaler,
    fit_vocabulary,
)

ROOT = Path(__file__).resolve().parents[4]
CSV_PATH = ROOT / "data" / "model" / "wp2_3_match_assignments.csv"
COHORT_SQL_PATH = ROOT / "backend" / "sql" / "wp2_1" / "01_model_shot_cohort.sql"

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
        "git_commit",
        "source_commit",
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
    out_dir: Path
    artifacts_dir: Path
    git_commit: str
    source_commit: str
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
    results_csv: Path


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
    """The full-logistic fields the results.csv row reads, structurally typed for the cast."""

    mean_log_loss: float
    pooled_oof: PooledOOFMetrics


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
        out_dir=Path(str(payload["out_dir"])),
        artifacts_dir=Path(str(payload["artifacts_dir"])),
        git_commit=str(payload["git_commit"]),
        source_commit=str(payload["source_commit"]),
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
        results_csv=Path(str(payload.get("results_csv", ROOT / "experiments" / "results.csv"))),
    )


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
) -> tuple[dict[str, object], str]:
    geometry_beats_constant = _replacement_rule(
        candidates["constant"], candidates["geometry_logistic"]
    )
    incumbent = "constant" if not geometry_beats_constant else "geometry_logistic"
    full_beats_incumbent = _replacement_rule(candidates[incumbent], candidates["full_logistic"])
    if full_beats_incumbent:
        incumbent = "full_logistic"
    return {
        "geometry_beats_constant": geometry_beats_constant,
        "full_beats_incumbent": full_beats_incumbent,
        "incumbent": incumbent,
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


def run_protocol(
    rows: Sequence[ShotRow],
    config: RunConfig,
) -> tuple[dict[str, object], LogisticModel]:
    """Run the locked protocol over development rows; returns (metrics, final refit model)."""
    rows_list = list(rows)
    n_folds = config.n_folds
    vocabulary = build_vocabulary(rows_list)

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

    full_columns = list(range(len(selected_folds[0].column_names)))
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

    final_model, coefficient_table, final_refit = _final_refit(
        rows_list, vocabulary, config, candidates["full_logistic"]
    )
    final_refit["model_pickle_sha256"] = _pickle_sha(final_model)

    d5 = _run_d5(
        candidates["full_logistic"],
        candidates["full_minus_presence"],
        {
            str(entry["feature"]): _sign(cast(float, entry["standardized_coefficient"]))
            for entry in coefficient_table
            if str(entry["feature"]).endswith("_presence")
        },
    )
    replacement, incumbent = _run_replacements(candidates)

    metrics: dict[str, object] = {
        "experiment_id": config.experiment_id,
        "git_commit": config.git_commit,
        "source_commit": config.source_commit,
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
        "replacement_rule": replacement,
        "incumbent": incumbent,
        "presence_report": _presence_report(rows_list, n_folds),
        "coefficients": coefficient_table,
        "final_dev_refit": final_refit,
    }
    return metrics, final_model


def _final_refit(
    rows: Sequence[ShotRow],
    vocabulary: Vocabulary,
    config: RunConfig,
    full_metrics: Mapping[str, object],
) -> tuple[LogisticModel, list[dict[str, object]], dict[str, object]]:
    scaler = fit_scaler(rows)
    X, column_names = encode_rows(rows, vocabulary, scaler)
    y = np.asarray([row.y for row in rows], dtype=np.int_)
    best_c = cast(float, full_metrics["best_c"])
    model = fit_logistic(X, y, best_c, random_state=config.random_seed)
    coef = model.estimator.coef_[0]
    table: list[dict[str, object]] = []
    for index, name in enumerate(column_names):
        value = float(coef[index])
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
            "n_training_rows": len(rows),
            "model_pickle_sha256": "",
        },
    )


def _pickle_sha(model: object) -> str:
    return hashlib.sha256(pickle.dumps(model, protocol=5)).hexdigest()


def write_experiment(metrics: Mapping[str, object], model: object, config: RunConfig) -> list[Path]:
    config.out_dir.mkdir(parents=True, exist_ok=True)
    config.artifacts_dir.mkdir(parents=True, exist_ok=True)

    candidates = cast(Mapping[str, object], metrics["candidates"])
    full_candidate = cast(_CandidateReadOut, candidates["full_logistic"])
    incumbent = cast(str, metrics["incumbent"])

    (config.out_dir / "metrics.json").write_bytes(canonical_metrics_json(metrics))

    config_dict = {
        "experiment_id": config.experiment_id,
        "out_dir": str(config.out_dir),
        "artifacts_dir": str(config.artifacts_dir),
        "git_commit": config.git_commit,
        "source_commit": config.source_commit,
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
        "results_csv": str(config.results_csv),
    }
    (config.out_dir / "config.json").write_bytes(canonical_metrics_json(config_dict))

    (config.out_dir / "notes.md").write_text(_notes_template(config), encoding="utf-8")

    pickle_bytes = pickle.dumps(model, protocol=5)
    pickle_path = config.artifacts_dir / "model.pkl"
    pickle_path.write_bytes(pickle_bytes)
    artifact_manifest = {
        "model_pickle_path": str(pickle_path),
        "model_pickle_sha256": hashlib.sha256(pickle_bytes).hexdigest(),
        "recreation_command": (
            f"uv run python -m touchline.modeling.train --config {config.out_dir / 'config.json'}"
        ),
        "coefficients_json": str(config.out_dir / "metrics.json"),
    }
    (config.out_dir / "artifact-manifest.json").write_bytes(
        canonical_metrics_json(artifact_manifest)
    )

    results_row = {
        "experiment_id": config.experiment_id,
        "date_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": config.git_commit,
        "dataset_id": "wp2_3_split_lock",
        "query_hash": config.cohort_sql_sha256,
        "feature_set": "geometry+categoricals+presence-indicators",
        "split_strategy": "wp2_3_tournament_split",
        "model": "regularized-logistic",
        "seed": config.random_seed,
        "primary_metric": "mean_log_loss",
        "primary_value": full_candidate["mean_log_loss"],
        "brier": full_candidate["pooled_oof"]["brier"],
        "log_loss": full_candidate["pooled_oof"]["log_loss"],
        "calibration_summary": "five-bin equal-width; D11 support applied",
        "status": "complete",
        "decision": incumbent,
        "notes_path": str(config.out_dir / "notes.md"),
    }
    _append_results_csv(config.results_csv, results_row)
    return [
        config.out_dir / "metrics.json",
        config.out_dir / "config.json",
        config.out_dir / "notes.md",
        config.out_dir / "artifact-manifest.json",
        pickle_path,
    ]


RESULTS_CSV_HEADER = (
    "experiment_id,date_utc,git_commit,dataset_id,query_hash,feature_set,split_strategy,"
    "model,seed,primary_metric,primary_value,brier,log_loss,calibration_summary,status,"
    "decision,notes_path"
)


def _append_results_csv(path: Path, row: Mapping[str, object]) -> None:
    header = RESULTS_CSV_HEADER
    keys = header.split(",")
    values = ",".join(str(row[key]) for key in keys)
    if not path.exists() or path.read_text(encoding="utf-8").strip() == "":
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(header + "\n")
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(values + "\n")


def _notes_template(config: RunConfig) -> str:
    return (
        "# WP2.4 experiment run\n\n"
        f"Experiment: {config.experiment_id}\n\n"
        "Hypothesis: a regularized logistic regression over the locked feature set beats both "
        "baselines under PLAN §4.1; presence indicators are admissible only if the D5 protocol "
        "passes.\n\n"
        "See metrics.json for the measured protocol result; see "
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
    args = parser.parse_args(argv)

    config = _load_config(Path(args.config))
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

    metrics, final_model = run_protocol(rows, config)
    write_experiment(metrics, final_model, config)
    d5_result = cast(Mapping[str, object], metrics["d5"])
    print(f"Wrote experiment record: {config.out_dir}")
    print(f"Incumbent: {metrics['incumbent']} | D5 include: {d5_result['include']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
