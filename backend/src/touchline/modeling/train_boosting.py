"""WP2.5 training entry point: one gradient-boosting candidate on the locked development split.

``python -m touchline.modeling.train_boosting --config <path>`` reads a JSON config, verifies the
pinned WP2.3 artifacts (byte-pin + canonical LF), loads **development rows only** through the WP2.1
cohort query, and runs the locked protocol with one added candidate:

- the four WP2.4 candidates (constant, geometry-only logistic, full logistic, full-minus-presence
  logistic) **re-fitted in this same process on these same folds**, so the comparison never depends
  on floats read from another run;
- ``hist_gbm`` — a ``HistGradientBoostingClassifier`` tuned over the twelve-point declared grid
  (D14) on WP2.4's shipped feature columns (D13);
- PLAN §4.1 applied **twice** (D18): chain A is WP2.4's chain extended by one step and is published
  for continuity, chain B compares the booster directly against the shipped logistic and is the
  decision of record;
- the D19 calibration-support diagnostic, which reports the supported-bin asymmetry without any
  decision reading it.

The §4.1 rule body, the D11 support floor and the five-bin reliability table are inherited
unmodified from ``touchline.modeling.protocol``. Nothing here fits calibration, reads a holdout or
calibration row, or re-runs WP2.4's D5 protocol — WP2.5 inherits D5's outcome.

All decisions are pre-registered in ADR 0011 and the WP2.5 modelling contract; this module only
applies them. It never writes to the database: the connection is opened READ ONLY and the load is a
``SET TRANSACTION READ ONLY`` read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast

import numpy as np
from threadpoolctl import threadpool_limits  # type: ignore[import-untyped]

from touchline.modeling.artifact import (
    BoostingBundle,
    boosting_artifact_schema_version,
)
from touchline.modeling.boosting import (
    EARLY_STOPPING,
    GBM_GRID,
    L2_REGULARIZATION,
    MAX_BINS,
    MAX_ITER,
    BoostingParams,
    fit_boosting,
    select_hyperparameters,
)
from touchline.modeling.dataset import (
    load_development_cohort,
    parse_match_assignments,
    verify_assignments_csv,
    verify_cohort_sql,
    verify_development_anchor,
)
from touchline.modeling.experiment import (
    ROOT,
    Provenance,
    abs_path,
    open_db,
    pickle_sha,
    record_path,
    replace_results_csv,
    resolve_provenance,
)
from touchline.modeling.logistic import L2_C_GRID, fit_logistic, select_regularization
from touchline.modeling.metrics import (
    PooledOOFMetrics,
    ReliabilityEntry,
    canonical_metrics_json,
)
from touchline.modeling.preprocessing import (
    CATEGORICAL_FIELDS,
    CONTINUOUS_FIELDS,
    PRESENCE_SOURCE_FIELDS,
    RARE_MIN_DEV_ROWS,
    ShotRow,
    Vocabulary,
    encode_rows,
    fit_scaler,
    fit_vocabulary,
)
from touchline.modeling.protocol import (
    D11_MIN_SUPPORT,
    FloatArray,
    FoldData,
    build_folds,
    evaluate_constant,
    replacement_rule,
    restrict_folds,
    run_replacement_chain,
    score_folds,
)

CSV_PATH = ROOT / "data" / "model" / "wp2_3_match_assignments.csv"
COHORT_SQL_PATH = ROOT / "backend" / "sql" / "wp2_1" / "01_model_shot_cohort.sql"
DEFAULT_RESULTS_CSV = "experiments/results.csv"

#: The only model family this entry point runs. Recorded in the config and asserted on load.
MODEL_FAMILY = "hist-gradient-boosting"

#: D20: every fit runs single-threaded. Histogram boosting sums gradients in a thread-dependent
#: order, so byte-identical metrics across runs are only claimable with the thread count pinned.
THREAD_LIMIT = 1

#: The candidate key for the boosting model, and the WP2.4 candidate it is compared against.
GBM_KEY = "hist_gbm"
SHIPPED_LOGISTIC_KEY = "full_minus_presence"

#: D18 chain A: WP2.4's chain, extended by exactly one step.
CHAIN_A_ORDER = ("constant", "geometry_logistic", SHIPPED_LOGISTIC_KEY, GBM_KEY)

REQUIRED_CONFIG_KEYS = frozenset(
    {
        "experiment_id",
        "out_dir",
        "artifacts_dir",
        "data_source_commit",
        "db_url_env",
        "assignments_sha256",
        "cohort_sql_sha256",
        "model_family",
        "c_grid",
        "gbm_grid",
        "random_seed",
        "n_folds",
        "expected_shots",
        "expected_matches",
        "expected_fold_sizes",
        "bin_count",
    }
)


@dataclass(frozen=True)
class BoostingRunConfig:
    """WP2.5's run configuration.

    Carries ``c_grid`` as well as ``gbm_grid`` because the WP2.4 logistic candidates are re-fitted
    here on the same folds: the comparison must be produced by one process from one population.
    """

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
    model_family: str
    c_grid: tuple[float, ...]
    gbm_grid: tuple[BoostingParams, ...]
    random_seed: int
    n_folds: int
    expected_shots: int
    expected_matches: int
    expected_fold_sizes: Mapping[int, int]
    bin_count: int
    results_csv: str


class _CandidateReadOut(TypedDict):
    """The fields the results.csv row reads from a candidate, structurally typed for the cast."""

    mean_log_loss: float
    pooled_oof: PooledOOFMetrics


def _parse_grid_point(payload: Mapping[str, object]) -> BoostingParams:
    return BoostingParams(
        learning_rate=float(cast(float, payload["learning_rate"])),
        max_leaf_nodes=int(cast(int, payload["max_leaf_nodes"])),
        min_samples_leaf=int(cast(int, payload["min_samples_leaf"])),
    )


def _load_config(path: Path) -> BoostingRunConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"config {path} must be a JSON object")
    missing = REQUIRED_CONFIG_KEYS - set(payload)
    if missing:
        raise ValueError(f"config {path} is missing required keys: {sorted(missing)}")
    if str(payload["model_family"]) != MODEL_FAMILY:
        raise ValueError(
            f"model_family in config {payload['model_family']!r} is not {MODEL_FAMILY!r}; "
            "this entry point runs exactly one family"
        )
    c_grid = tuple(float(c) for c in payload["c_grid"])
    if c_grid != L2_C_GRID:
        raise ValueError(
            f"C grid in config {c_grid} does not match the pre-registered D10 grid {L2_C_GRID}"
        )
    gbm_grid = tuple(_parse_grid_point(point) for point in payload["gbm_grid"])
    if gbm_grid != GBM_GRID:
        raise ValueError(
            f"boosting grid in config has {len(gbm_grid)} point(s) that do not match the "
            f"pre-registered D14 grid of {len(GBM_GRID)}; the search space is not tunable at run "
            "time"
        )
    if int(payload["bin_count"]) != 5:
        raise ValueError("reliability bin count is locked at five (ADR 0004)")
    fold_sizes = {
        int(str(fold)): int(size) for fold, size in payload["expected_fold_sizes"].items()
    }
    return BoostingRunConfig(
        experiment_id=str(payload["experiment_id"]),
        out_dir=str(payload["out_dir"]),
        artifacts_dir=str(payload["artifacts_dir"]),
        # Provenance is derived at run time (see resolve_provenance); JSON-supplied values are not
        # trusted as the authoritative implementation revision.
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
        model_family=MODEL_FAMILY,
        c_grid=c_grid,
        gbm_grid=gbm_grid,
        random_seed=int(payload["random_seed"]),
        n_folds=int(payload["n_folds"]),
        expected_shots=int(payload["expected_shots"]),
        expected_matches=int(payload["expected_matches"]),
        expected_fold_sizes=fold_sizes,
        bin_count=int(payload["bin_count"]),
        results_csv=str(payload.get("results_csv", DEFAULT_RESULTS_CSV)),
    )


def apply_provenance(config: BoostingRunConfig, provenance: Provenance) -> BoostingRunConfig:
    """Fold the derived reproduction identity back into the run config."""
    return replace(
        config,
        code_commit=provenance.code_commit,
        reproduction_commit=provenance.reproduction_commit,
        input_config_sha256=provenance.input_config_sha256,
        uv_lock_sha256=provenance.uv_lock_sha256,
        runtime_fingerprint=provenance.runtime_fingerprint,
    )


def build_vocabulary(rows: Sequence[ShotRow]) -> Vocabulary:
    """Label-free dev-wide vocabulary from development rows only (D8, inherited)."""
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        for field in CATEGORICAL_FIELDS:
            key = (field, str(getattr(row, field)))
            counts[key] = counts.get(key, 0) + 1
    return fit_vocabulary(counts, threshold=RARE_MIN_DEV_ROWS)


def _score_logistic(folds: Sequence[FoldData], best_c: float, seed: int) -> dict[str, object]:
    """Out-of-fold logistic scores at a fixed C. Each fold fits on its training rows only."""

    def predict(fold: FoldData) -> FloatArray:
        model = fit_logistic(fold.X_train, fold.y_train, best_c, random_state=seed)
        return model.predict_proba(fold.X_val)

    metrics = score_folds(folds, predict)
    metrics["best_c"] = best_c
    return metrics


def _score_boosting(
    folds: Sequence[FoldData], params: BoostingParams, seed: int
) -> dict[str, object]:
    """Out-of-fold boosting scores at one grid point. Each fold fits on its training rows only."""

    def predict(fold: FoldData) -> FloatArray:
        model = fit_boosting(fold.X_train, fold.y_train, params, random_state=seed)
        return model.predict_proba(fold.X_val)

    metrics = score_folds(folds, predict)
    metrics["hyperparameters"] = params.as_dict()
    return metrics


def _selected_c(folds: Sequence[FoldData], config: BoostingRunConfig) -> float:
    fold_specs = [(f.X_train, f.X_val, f.y_train, f.y_val) for f in folds]
    best_c, _scored = select_regularization(
        fold_specs, config.c_grid, random_state=config.random_seed
    )
    return best_c


def _paired_calibration_support(
    incumbent: Mapping[str, object],
    candidate: Mapping[str, object],
    min_support: int,
) -> dict[str, object]:
    """D19: report the supported-bin asymmetry. **No decision reads this.**

    A booster spreads its predictions wider than a logistic model, so the two candidates do not
    clear the D11 floor in the same bins. The §4.1 rule keeps reading each candidate's own
    ``max_abs_deviation_supported``; this block exists so a reader can see how much of the
    calibration comparison rested on a shared basis and how much did not.
    """
    left = cast(Sequence[ReliabilityEntry], incumbent["reliability"])
    right = cast(Sequence[ReliabilityEntry], candidate["reliability"])
    paired: list[int] = []
    left_deviations: list[float] = []
    right_deviations: list[float] = []
    for a, b in zip(left, right, strict=True):
        a_ok = a["count"] >= min_support and a["observed_rate"] is not None
        b_ok = b["count"] >= min_support and b["observed_rate"] is not None
        if not (a_ok and b_ok):
            continue
        a_mean, a_obs = a["mean_prediction"], a["observed_rate"]
        b_mean, b_obs = b["mean_prediction"], b["observed_rate"]
        if a_mean is None or a_obs is None or b_mean is None or b_obs is None:
            continue
        paired.append(int(a["bin"]))
        left_deviations.append(abs(a_mean - a_obs))
        right_deviations.append(abs(b_mean - b_obs))
    return {
        "note": (
            "diagnostic only; the PLAN 4.1 decision reads each candidate's own "
            "max_abs_deviation_supported, which is unchanged"
        ),
        "min_support": min_support,
        "paired_supported_bins": paired,
        "paired_supported_bin_count": len(paired),
        "incumbent_supported_bins": int(cast(int, incumbent["supported_bins"])),
        "candidate_supported_bins": int(cast(int, candidate["supported_bins"])),
        "incumbent_max_abs_deviation_paired": (
            float(max(left_deviations)) if left_deviations else None
        ),
        "candidate_max_abs_deviation_paired": (
            float(max(right_deviations)) if right_deviations else None
        ),
    }


def run_protocol(
    rows: Sequence[ShotRow],
    config: BoostingRunConfig,
) -> tuple[dict[str, object], BoostingBundle]:
    """Run the WP2.5 protocol; returns (metrics, the boosting inference bundle).

    Every fit runs single-threaded (D20). The four WP2.4 candidates are re-fitted here so all five
    candidates are scored on byte-identical encoded matrices from one population.
    """
    with threadpool_limits(limits=THREAD_LIMIT):
        return _run_protocol_unlimited(rows, config)


def _run_protocol_unlimited(
    rows: Sequence[ShotRow],
    config: BoostingRunConfig,
) -> tuple[dict[str, object], BoostingBundle]:
    rows_list = list(rows)
    n_folds = config.n_folds
    seed = config.random_seed
    vocabulary = build_vocabulary(rows_list)
    all_columns = vocabulary.column_names()
    scaler_all = fit_scaler(rows_list)

    selected_folds = build_folds(rows_list, vocabulary, n_folds)

    # Candidate column subsets are resolved **by name**, never by hard-coded position: a change to
    # the encoder's column order would otherwise silently redefine the locked feature sets while
    # every downstream record still claimed them. ``list.index`` raises loudly on a missing column.
    full_columns = list(range(len(all_columns)))
    geometry_columns = [all_columns.index(name) for name in CONTINUOUS_FIELDS]
    presence_names = [f"{field}_presence" for field in PRESENCE_SOURCE_FIELDS]
    presence_columns = [all_columns.index(name) for name in presence_names]
    minus_columns = [i for i in full_columns if i not in presence_columns]

    geometry_folds = restrict_folds(selected_folds, geometry_columns)
    full_folds = restrict_folds(selected_folds, full_columns)
    minus_folds = restrict_folds(selected_folds, minus_columns)

    candidates: dict[str, Mapping[str, object]] = {}
    candidates["constant"] = evaluate_constant(rows_list, n_folds)
    candidates["geometry_logistic"] = _score_logistic(
        geometry_folds, _selected_c(geometry_folds, config), seed
    )
    candidates["full_logistic"] = _score_logistic(full_folds, _selected_c(full_folds, config), seed)
    candidates[SHIPPED_LOGISTIC_KEY] = _score_logistic(
        minus_folds, _selected_c(minus_folds, config), seed
    )

    # D13: the booster consumes WP2.4's shipped columns, so the two candidates differ in exactly
    # one thing — the estimator.
    gbm_specs = [(f.X_train, f.X_val, f.y_train, f.y_val) for f in minus_folds]
    best_params, gbm_search = select_hyperparameters(gbm_specs, config.gbm_grid, random_state=seed)
    candidates[GBM_KEY] = _score_boosting(minus_folds, best_params, seed)

    # D18 chain A: WP2.4's chain extended by one step, each step against the running incumbent.
    chain_a_outcomes, protocol_incumbent = run_replacement_chain(candidates, list(CHAIN_A_ORDER))
    chain_a = {
        "order": list(CHAIN_A_ORDER),
        "geometry_beats_constant": chain_a_outcomes[0],
        "shipped_beats_incumbent": chain_a_outcomes[1],
        "gbm_beats_protocol_incumbent": chain_a_outcomes[2],
        "protocol_incumbent": protocol_incumbent,
        "note": (
            "continuity with the WP2.4 record; the first two outcomes must reproduce it. This "
            "chain is not the selection - see replacement_chain_b."
        ),
    }

    # D18 chain B: the decision of record, against PLAN 4.1's literal incumbent.
    gbm_beats_logistic = replacement_rule(candidates[SHIPPED_LOGISTIC_KEY], candidates[GBM_KEY])
    selection_incumbent = GBM_KEY if gbm_beats_logistic else SHIPPED_LOGISTIC_KEY
    chain_b = {
        "incumbent": SHIPPED_LOGISTIC_KEY,
        "candidate": GBM_KEY,
        "gbm_beats_shipped_logistic": gbm_beats_logistic,
        "selection_incumbent": selection_incumbent,
        "note": "the PLAN 4.1 decision of record for WP2.5 (ADR 0011 D-A)",
    }

    # Final refit of the boosting candidate over all development rows: its selected grid point, its
    # exact column subset, the all-development scaler and the locked development vocabulary.
    full_encoded, _ = encode_rows(rows_list, vocabulary, scaler_all)
    subset = full_encoded[:, minus_columns]
    y_all = np.asarray([row.y for row in rows_list], dtype=np.int_)
    ship_model = fit_boosting(subset, y_all, best_params, random_state=seed)

    bundle = BoostingBundle(
        schema_version=boosting_artifact_schema_version,
        experiment_id=config.experiment_id,
        shipped_candidate=GBM_KEY,
        hyperparameters={k: float(v) for k, v in best_params.as_dict().items()},
        code_commit=config.code_commit,
        reproduction_commit=config.reproduction_commit,
        data_source_commit=config.data_source_commit,
        cohort_sql_sha256=config.cohort_sql_sha256,
        assignments_sha256=config.assignments_sha256,
        input_config_sha256=config.input_config_sha256,
        uv_lock_sha256=config.uv_lock_sha256,
        estimator=ship_model.estimator,
        scaler=scaler_all,
        vocabulary=vocabulary,
        all_columns=tuple(all_columns),
        selected_columns=tuple(all_columns[index] for index in minus_columns),
        selected_indices=tuple(int(index) for index in minus_columns),
        reference_levels=dict(vocabulary.reference),
        rare_mapping={field: tuple(levels) for field, levels in vocabulary.rare_members.items()},
    )

    metrics: dict[str, object] = {
        "experiment_id": config.experiment_id,
        "code_commit": config.code_commit,
        "reproduction_commit": config.reproduction_commit,
        "data_source_commit": config.data_source_commit,
        "input_config_path": record_path(config.input_config_path),
        "input_config_sha256": config.input_config_sha256,
        "uv_lock_sha256": config.uv_lock_sha256,
        "runtime_fingerprint": config.runtime_fingerprint,
        "cohort_sql_sha256": config.cohort_sql_sha256,
        "assignments_sha256": config.assignments_sha256,
        "n_rows": len(rows_list),
        "n_matches": len({row.match_id for row in rows_list}),
        "model_family": config.model_family,
        "c_grid": list(config.c_grid),
        "gbm_grid": [point.as_dict() for point in config.gbm_grid],
        "gbm_grid_size": len(config.gbm_grid),
        "gbm_fixed_hyperparameters": {
            "max_iter": MAX_ITER,
            "l2_regularization": L2_REGULARIZATION,
            "max_bins": MAX_BINS,
            "early_stopping": EARLY_STOPPING,
        },
        "random_seed": seed,
        "bin_count": config.bin_count,
        "d11_min_support": D11_MIN_SUPPORT,
        "thread_limit": THREAD_LIMIT,
        "vocabulary": vocabulary.as_dict(),
        "candidates": candidates,
        "gbm_search": gbm_search,
        "gbm_selected_hyperparameters": best_params.as_dict(),
        "artifact_candidate": GBM_KEY,
        "shipped_feature_set": "geometry+categoricals",
        "shipped_feature_columns": [all_columns[index] for index in minus_columns],
        "replacement_chain_a": chain_a,
        "replacement_chain_b": chain_b,
        "protocol_incumbent": protocol_incumbent,
        "shipped_candidate": selection_incumbent,
        "calibration_support_diagnostic": _paired_calibration_support(
            candidates[SHIPPED_LOGISTIC_KEY], candidates[GBM_KEY], D11_MIN_SUPPORT
        ),
        "model_pickle_sha256": pickle_sha(bundle),
    }
    return metrics, bundle


def write_experiment(
    metrics: Mapping[str, object], bundle: BoostingBundle, config: BoostingRunConfig
) -> list[Path]:
    """Write the WP2.5 experiment record and one authoritative results row."""
    out = abs_path(config.out_dir)
    art = abs_path(config.artifacts_dir)
    out.mkdir(parents=True, exist_ok=True)
    art.mkdir(parents=True, exist_ok=True)

    selected_key = cast(str, metrics["shipped_candidate"])
    candidates = cast(Mapping[str, object], metrics["candidates"])
    selected_metrics = cast(_CandidateReadOut, candidates[selected_key])

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
        "out_dir": record_path(config.out_dir),
        "artifacts_dir": record_path(config.artifacts_dir),
        "code_commit": config.code_commit,
        "reproduction_commit": config.reproduction_commit,
        "data_source_commit": config.data_source_commit,
        "input_config_path": record_path(config.input_config_path),
        "input_config_sha256": config.input_config_sha256,
        "uv_lock_sha256": config.uv_lock_sha256,
        "runtime_fingerprint": config.runtime_fingerprint,
        "db_url_env": config.db_url_env,
        "assignments_sha256": config.assignments_sha256,
        "cohort_sql_sha256": config.cohort_sql_sha256,
        "model_family": config.model_family,
        "c_grid": list(config.c_grid),
        "gbm_grid": [point.as_dict() for point in config.gbm_grid],
        "random_seed": config.random_seed,
        "n_folds": config.n_folds,
        "expected_shots": config.expected_shots,
        "expected_matches": config.expected_matches,
        "expected_fold_sizes": dict(config.expected_fold_sizes),
        "bin_count": config.bin_count,
        "thread_limit": THREAD_LIMIT,
        "results_csv": record_path(config.results_csv),
        "artifact_candidate": metrics["artifact_candidate"],
        "shipped_candidate": selected_key,
        "shipped_feature_set": metrics["shipped_feature_set"],
        "shipped_feature_columns": list(cast(list[object], metrics["shipped_feature_columns"])),
        "gbm_selected_hyperparameters": metrics["gbm_selected_hyperparameters"],
        "protocol_incumbent": metrics["protocol_incumbent"],
    }
    (out / "config.json").write_bytes(canonical_metrics_json(config_dict))

    (out / "notes.md").write_text(_notes_template(config), encoding="utf-8")

    pickle_path = art / "model.pkl"
    pickle_path.write_bytes(pickle_bytes)
    input_cfg_posix = record_path(config.input_config_path)
    artifact_manifest = {
        "experiment_id": config.experiment_id,
        "code_commit": config.code_commit,
        "reproduction_commit": config.reproduction_commit,
        "data_source_commit": config.data_source_commit,
        "input_config_path": input_cfg_posix,
        "input_config_sha256": config.input_config_sha256,
        "uv_lock_sha256": config.uv_lock_sha256,
        "runtime_fingerprint": config.runtime_fingerprint,
        "boosting_artifact_schema_version": boosting_artifact_schema_version,
        "model_family": config.model_family,
        "artifact_candidate": metrics["artifact_candidate"],
        "shipped_candidate": selected_key,
        "shipped_feature_set": metrics["shipped_feature_set"],
        "shipped_feature_columns": list(cast(list[object], metrics["shipped_feature_columns"])),
        "gbm_selected_hyperparameters": metrics["gbm_selected_hyperparameters"],
        "model_pickle_path": record_path(pickle_path),
        "model_pickle_sha256": bundle_hash,
        "recreation": {
            "checkout": f"git checkout {config.reproduction_commit}",
            "sync": "uv sync --locked",
            "database": (
                "set TOUCHLINE_FULL_COHORT_DB_URL to the local ingested four-tournament database"
            ),
            "run": (
                f"uv run python -m touchline.modeling.train_boosting --config {input_cfg_posix}"
            ),
        },
        "recreation_command": (
            f"uv run python -m touchline.modeling.train_boosting --config {input_cfg_posix}"
        ),
        "coefficients_json": record_path(out / "metrics.json"),
    }
    (out / "artifact-manifest.json").write_bytes(canonical_metrics_json(artifact_manifest))

    # The results index keeps WP2.4's twenty-five-column header. Widening it would force a
    # positional rewrite of the committed WP2.4 row, which is published evidence for a closed work
    # package; the two logistic-shaped columns therefore carry an explicit "n/a".
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
        "model": MODEL_FAMILY,
        "seed": config.random_seed,
        "primary_metric": "mean_log_loss",
        "primary_value": selected_metrics["mean_log_loss"],
        "brier": selected_metrics["pooled_oof"]["brier"],
        "log_loss": selected_metrics["pooled_oof"]["log_loss"],
        "protocol_incumbent": metrics["protocol_incumbent"],
        "shipped_candidate": selected_key,
        "d5_include": "n/a",
        "shipped_best_c": "n/a",
        "model_pickle_sha256": bundle_hash,
        "calibration_summary": "five-bin equal-width; D11 support applied",
        "status": "complete",
        "notes_path": record_path(out / "notes.md"),
    }
    replace_results_csv(config.results_csv, results_row)
    return [
        out / "metrics.json",
        out / "config.json",
        out / "notes.md",
        out / "artifact-manifest.json",
        pickle_path,
    ]


def _notes_template(config: BoostingRunConfig) -> str:
    """The public run note. Paths go through ``record_path``; pointers stay inside the publication.

    ``notes.md`` is committed and published, so it obeys the committed-record path contract: the
    input-config path is written in the canonical repository-relative POSIX form, and readers are
    pointed only at committed public evidence.
    """
    return (
        "# WP2.5 experiment run\n\n"
        f"Experiment: {config.experiment_id}\n\n"
        f"Code commit: {config.code_commit}\n"
        f"Reproduction commit: {config.reproduction_commit}\n"
        f"Input config: {record_path(config.input_config_path)}\n\n"
        "Hypothesis: one gradient-boosting model, tuned over a twelve-point declared grid on the "
        "locked development folds and the shipped WP2.4 feature columns, replaces the regularized "
        "logistic regression under PLAN 4.1. The rule is applied twice: continuity with the WP2.4 "
        "chain, and a direct comparison against the shipped logistic which is the decision of "
        "record. A negative result is published as a result.\n\n"
        "Published evidence for this run:\n\n"
        "- `metrics.json` — the measured protocol result, both replacement chains, the declared "
        "grid and its scores;\n"
        "- `artifact-manifest.json` — the boosting bundle identity, its hashes and the recreation "
        "commands;\n"
        "- `config.json` — the resolved run-configuration snapshot;\n"
        "- `reports/wp2.5-gradient-boosting-evidence.md` — the reviewable WP2.5 evidence "
        "report.\n\n"
        "The pre-registered D12-D21 decisions live in the repository-internal modelling contract, "
        "which is deliberately not published; every decision they fix is restated in the public "
        "evidence report above.\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="touchline.modeling.train_boosting")
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

    # The fingerprint is derived inside the thread limit so the recorded threadpool state is the
    # one the fits actually ran under (D20).
    with threadpool_limits(limits=THREAD_LIMIT):
        provenance = resolve_provenance(config, code_commit_override=args.code_commit)
    config = apply_provenance(config, provenance)

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
    conn = open_db(db_url_source, schema_override)
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
    print(f"Wrote experiment record: {record_path(config.out_dir)}")
    print(
        f"Selected grid point: {metrics['gbm_selected_hyperparameters']} "
        f"| chain B decision: {metrics['shipped_candidate']} "
        f"| chain A incumbent: {metrics['protocol_incumbent']}"
    )
    print(f"code_commit: {provenance.code_commit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
