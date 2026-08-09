"""Supervised WP2.7 calibration and one-time holdout runners.

Real execution is bound to byte-pinned registered phase configs. Tests may inject synthetic loaders
and self-contained configs, but neither CLI exposes model/input-path nor bootstrap overrides.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

import numpy as np
from scipy.special import expit  # type: ignore[import-untyped]

from touchline.modeling.calibration import (
    ADOPTION_TOLERANCE,
    CALIBRATION_RULE_VERSION,
    RAW_ANCHOR_BIN_EDGES,
    BaseModelPins,
    CalibrationDecision,
    FrozenBaseModel,
    assert_frozen_base_unchanged,
    decide_calibration_adoption,
    exact_payload_sha256,
    fit_platt,
    freeze_base_model,
    load_calibration_decision,
    platt_parameter_digest,
    verify_calibration_decision,
    write_calibration_decision,
)
from touchline.modeling.dataset import (
    MatchAssignments,
    load_partition_cohort,
    parse_match_assignments,
    verify_assignments_csv,
    verify_cohort_sql,
)
from touchline.modeling.experiment import (
    ROOT,
    Provenance,
    abs_path,
    historical_git_blob_sha256,
    open_db,
    record_path,
    resolve_provenance,
    sha256_bytes,
)
from touchline.modeling.holdout import (
    BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    EXPECTED_HOLDOUT_STAGES,
    SLICE_MIN_GOALS,
    SLICE_MIN_MATCHES,
    SLICE_MIN_MISSES,
    SLICE_MIN_SHOTS,
    HoldoutAccessAudit,
    HoldoutAccessSession,
    evaluate_holdout_rows,
    finalize_holdout_audit,
    membership_digest,
    write_holdout_evidence,
)
from touchline.modeling.preprocessing import ShotRow
from touchline.modeling.protocol import D11_MIN_SUPPORT

__all__ = [
    "CALIBRATION_EXPECTED_MATCHES",
    "CALIBRATION_EXPECTED_SHOTS",
    "DEFAULT_CALIBRATION_CONFIG_PATH",
    "DEFAULT_DECISION_PATH",
    "DEFAULT_HOLDOUT_CONFIG_PATH",
    "DEFAULT_HOLDOUT_OUTPUT_DIR",
    "HOLDOUT_EXPECTED_MATCHES",
    "HOLDOUT_EXPECTED_SHOTS",
    "run_calibration_phase",
    "run_holdout_phase",
]

DEFAULT_CALIBRATION_CONFIG_PATH = ROOT / "experiments/run-configs/wp2_7-calibration.json"
DEFAULT_HOLDOUT_CONFIG_PATH = ROOT / "experiments/run-configs/wp2_7-holdout.json"
DEFAULT_CALIBRATION_CONFIG_SHA256 = (
    "ca3a4a1fe380338837bc718ffdb313324639e28e9b16d6b171467aee07214cb5"
)
DEFAULT_HOLDOUT_CONFIG_SHA256 = "d77187ad0bf7e5053d73c2debe0a61b8e1464885b16601d025f43d811267589b"
EXPECTED_BASE_PIN_PAYLOAD: dict[str, object] = {
    "artifact_path": "artifacts/models/exp-20260805-wp2_4-baselines/model.pkl",
    "artifact_manifest_path": (
        "experiments/shot_quality/exp-20260805-wp2_4-baselines/artifact-manifest.json"
    ),
    "artifact_schema_version": 1,
    "model_pickle_sha256": "9aeac9468c00bd1b93c771e454e48ca29e2eb759cf71836182a782d674bfadca",
    "artifact_manifest_sha256": "62cade6c3db5d741039de8f1ad53010319f422dcb942c96f16f1db8a498e8e79",
    "experiment_id": "exp-20260805-wp2_4-baselines",
    "candidate": "full_minus_presence",
    "shipped_feature_set": "geometry+categoricals",
    "best_c": 0.1,
    "data_source_commit": "b0bc9f22dd77c206ddedc1d742893b3bbe64baec",
    "cohort_sql_sha256": "301d8a620b60d8da6011c7c4d12ef8108c658df4d923f612c3e3bf9e0427978e",
    "assignments_sha256": "e2d5517d96aa81d2229e1ef00a3c692f44f280630c3e75b7f6735e7cdc1787d8",
    "code_commit": "81d4a56395985cb427fbcd13f38a0eb8c42e8be6",
    "reproduction_commit": "81d4a56395985cb427fbcd13f38a0eb8c42e8be6",
    "input_config_sha256": "30d34981d957f2b7c3832b2fe347f10986a6f14e58cca98a4abba673a56b0b0e",
    "uv_lock_sha256": "58c4b2b39cf78d217284784ada544633ea7c145a9a5a0a6c4eb6312eb7ea3902",
}
EXPECTED_SPLIT_MANIFEST_SHA256 = "621d22b5c5eb3340387ccf00c13e4beeb57b644822ef54a821cd89cd7afce3aa"
DEFAULT_OUTPUT_DIR = ROOT / "experiments/shot_quality/exp-20260809-wp2_7-calibration-holdout"
DEFAULT_DECISION_PATH = DEFAULT_OUTPUT_DIR / "calibration-decision.json"
DEFAULT_HOLDOUT_OUTPUT_DIR = DEFAULT_OUTPUT_DIR
DEFAULT_DB_URL_ENV = "TOUCHLINE_FULL_COHORT_DB_URL"

CALIBRATION_EXPECTED_SHOTS = 1_430
CALIBRATION_EXPECTED_MATCHES = 64
HOLDOUT_EXPECTED_SHOTS = 1_304
HOLDOUT_EXPECTED_MATCHES = 51

WP27_SOURCE_PATHS = (
    "backend/src/touchline/modeling/wp2_7.py",
    "backend/src/touchline/modeling/calibration.py",
    "backend/src/touchline/modeling/holdout.py",
    "backend/src/touchline/modeling/artifact.py",
    "backend/src/touchline/modeling/dataset.py",
    "backend/src/touchline/modeling/preprocessing.py",
    "backend/src/touchline/modeling/metrics.py",
    "backend/src/touchline/modeling/protocol.py",
    "backend/src/touchline/modeling/experiment.py",
    "backend/src/touchline/features/geometry.py",
)


@dataclass(frozen=True)
class PhaseConfig:
    path: Path
    sha256: str
    payload: Mapping[str, object]

    def value(self, key: str) -> object:
        try:
            return self.payload[key]
        except KeyError as exc:
            raise RuntimeError(f"WP2.7 {self.payload.get('phase')} config lacks {key!r}") from exc

    def text(self, key: str) -> str:
        value = self.value(key)
        if not isinstance(value, str) or not value:
            raise RuntimeError(f"WP2.7 config field {key!r} must be a non-empty string")
        return value

    def path_value(self, key: str) -> Path:
        return abs_path(self.text(key))


@dataclass(frozen=True)
class _ProvenanceConfig:
    code_commit: str
    data_source_commit: str
    input_config_path: str
    require_clean_provenance: bool


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_phase_config(
    path: str | Path,
    phase: Literal["calibration", "holdout"],
    *,
    enforce_registered: bool,
) -> PhaseConfig:
    source = Path(path).resolve()
    try:
        raw = source.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read WP2.7 {phase} config {source}") from exc
    digest = hashlib.sha256(raw).hexdigest()
    if enforce_registered:
        expected_path = (
            DEFAULT_CALIBRATION_CONFIG_PATH
            if phase == "calibration"
            else DEFAULT_HOLDOUT_CONFIG_PATH
        ).resolve()
        expected_digest = (
            DEFAULT_CALIBRATION_CONFIG_SHA256
            if phase == "calibration"
            else DEFAULT_HOLDOUT_CONFIG_SHA256
        )
        if source != expected_path or digest != expected_digest:
            raise RuntimeError(
                f"real WP2.7 {phase} execution requires the byte-pinned registered config"
            )
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise RuntimeError(f"WP2.7 {phase} config has an unsupported schema")
    if payload.get("phase") != phase:
        raise RuntimeError(f"WP2.7 config phase is not {phase!r}")
    config = PhaseConfig(source, digest, payload)
    if enforce_registered and config.value("require_clean_provenance") is not True:
        raise RuntimeError("real WP2.7 execution requires clean provenance")
    if phase == "calibration":
        _validate_calibration_config(config)
    else:
        _validate_holdout_config(config)
    return config


def _validate_calibration_config(config: PhaseConfig) -> None:
    payload = config.payload
    expected = {
        "base_fit_scope": "development_only",
        "calibration_tournament": "WC2022",
        "holdout_tournament": "Euro2024",
        "calibration_rule_version": CALIBRATION_RULE_VERSION,
        "calibrator": "platt_sigmoid",
        "minimum_supported_bin_shots": D11_MIN_SUPPORT,
        "holdout_accessed": False,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise RuntimeError(f"WP2.7 calibration config violates the frozen {key} contract")
    if payload.get("raw_anchor_bin_edges") != list(RAW_ANCHOR_BIN_EDGES):
        raise RuntimeError("WP2.7 calibration config changes the raw-anchor bins")
    if payload.get("adoption_tolerance") != ADOPTION_TOLERANCE:
        raise RuntimeError("WP2.7 calibration config changes the adoption tolerance")
    frozen_base = payload.get("frozen_base")
    if not isinstance(frozen_base, Mapping):
        raise RuntimeError("WP2.7 calibration config lacks frozen_base pins")
    pins = BaseModelPins.from_mapping(frozen_base)
    if (
        config.sha256 == DEFAULT_CALIBRATION_CONFIG_SHA256
        and pins.as_dict() != EXPECTED_BASE_PIN_PAYLOAD
    ):
        raise RuntimeError("registered WP2.7 calibration config changes the frozen base pin")
    split_digest = config.text("split_manifest_sha256")
    if len(split_digest) != 64:
        raise RuntimeError("WP2.7 calibration config has a malformed split-manifest digest")
    if (
        config.sha256 == DEFAULT_CALIBRATION_CONFIG_SHA256
        and split_digest != EXPECTED_SPLIT_MANIFEST_SHA256
    ):
        raise RuntimeError("registered WP2.7 calibration config changes the split-manifest pin")


def _validate_holdout_config(config: PhaseConfig) -> None:
    payload = config.payload
    bootstrap = payload.get("bootstrap")
    if bootstrap != {
        "replicates": BOOTSTRAP_REPLICATES,
        "seed": BOOTSTRAP_SEED,
        "interval": "95_percentile",
    }:
        raise RuntimeError("WP2.7 holdout bootstrap must be exactly 2,000 replicates with seed 0")
    if payload.get("scoring_variants") != ["raw", "calibrated"]:
        raise RuntimeError("WP2.7 holdout may score only raw and calibrated logistic predictions")
    if payload.get("constant_baseline_included") is not False:
        raise RuntimeError("WP2.7 holdout config must exclude the constant baseline")
    if payload.get("prevalence_role") != "descriptive_context_only":
        raise RuntimeError("WP2.7 prevalence must remain descriptive context")
    if payload.get("one_supervised_execution") is not True:
        raise RuntimeError("WP2.7 holdout config must require one supervised execution")
    if payload.get("post_run_real_row_reload") is not False:
        raise RuntimeError("WP2.7 holdout config must forbid post-run real-row reload")
    if payload.get("distance_unit") != "StatsBomb coordinate units":
        raise RuntimeError("WP2.7 distance must use StatsBomb coordinate units")
    if payload.get("visible_angle_unit") != "radians":
        raise RuntimeError("WP2.7 visible angle must use radians")
    if payload.get("slice_support") != {
        "shots": SLICE_MIN_SHOTS,
        "goals": SLICE_MIN_GOALS,
        "misses": SLICE_MIN_MISSES,
        "matches": SLICE_MIN_MATCHES,
    }:
        raise RuntimeError("WP2.7 holdout config changes the pre-registered slice support")


def _resolve_execution_provenance(config: PhaseConfig) -> dict[str, object]:
    adapter = _ProvenanceConfig(
        code_commit=config.text("code_commit"),
        data_source_commit=config.text("data_source_commit"),
        input_config_path=config.path.as_posix(),
        require_clean_provenance=config.value("require_clean_provenance") is True,
    )
    resolved: Provenance = resolve_provenance(adapter)
    if resolved.input_config_sha256 != config.sha256:
        raise RuntimeError("resolved WP2.7 config digest changed during provenance capture")
    source_hashes = {path: sha256_bytes((ROOT / path).read_bytes()) for path in WP27_SOURCE_PATHS}
    if adapter.require_clean_provenance:
        registered_config_path = record_path(config.path)
        if (
            historical_git_blob_sha256(ROOT, resolved.code_commit, registered_config_path)
            != config.sha256
        ):
            raise RuntimeError("registered WP2.7 config is not byte-identical to the clean HEAD")
        for path, current_digest in source_hashes.items():
            if historical_git_blob_sha256(ROOT, resolved.code_commit, path) != current_digest:
                raise RuntimeError(f"WP2.7 source {path} is not byte-identical to the clean HEAD")
    payload = resolved.as_dict()
    payload.update(
        {
            "phase": config.text("phase"),
            "experiment_id": config.text("experiment_id"),
            "source_files_sha256": source_hashes,
            "source_bundle_sha256": exact_payload_sha256({"source_files_sha256": source_hashes}),
        }
    )
    return payload


def _assert_decision_execution_matches(
    decision: CalibrationDecision, current: Mapping[str, object]
) -> None:
    """Require the holdout code/lock identity to equal the identity that made the decision."""
    recorded = decision.payload.get("execution_provenance")
    if not isinstance(recorded, Mapping):
        raise RuntimeError("calibration decision lacks execution provenance")
    keys = (
        "data_source_commit",
        "uv_lock_sha256",
        "source_bundle_sha256",
        "source_files_sha256",
    )
    if any(recorded.get(key) != current.get(key) for key in keys):
        raise RuntimeError(
            "holdout execution code, source, or lockfile identity differs from the "
            "calibration decision"
        )


def _load_locked_inputs(config: PhaseConfig, pins: BaseModelPins) -> tuple[str, MatchAssignments]:
    assignments_path = config.path_value("assignments_path")
    cohort_sql_path = config.path_value("cohort_sql_path")
    split_manifest_path = config.path_value("split_manifest_path")
    if _sha256(split_manifest_path) != config.text("split_manifest_sha256"):
        raise RuntimeError("WP2.3 split manifest does not match the WP2.7 external pin")
    manifest = json.loads(split_manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise RuntimeError("WP2.3 split manifest must be a JSON object")
    expected = {
        "assignments_sha256": pins.assignments_sha256,
        "cohort_sql_sha256": pins.cohort_sql_sha256,
        "source_commit": pins.data_source_commit,
    }
    actual = {key: manifest.get(key) for key in expected}
    if actual != expected:
        raise RuntimeError("WP2.3 split/source lock does not match the externally pinned base")
    assignments_bytes = assignments_path.read_bytes()
    verify_assignments_csv(assignments_bytes, pins.assignments_sha256)
    sql = verify_cohort_sql(cohort_sql_path.read_bytes(), pins.cohort_sql_sha256)
    assignments = parse_match_assignments(assignments_bytes.decode("utf-8"))
    return sql, assignments


def _assert_partition_anchor(
    rows: Sequence[ShotRow],
    assignments: MatchAssignments,
    split: str,
    *,
    expected_shots: int | None,
    expected_matches: int | None,
) -> None:
    if split not in {"calibration", "holdout"}:
        raise RuntimeError(f"WP2.7 only admits calibration or holdout rows, got {split!r}")
    split_name = cast(Literal["calibration", "holdout"], split)
    expected_ids = assignments.ids_for(split_name)
    actual_ids = {row.match_id for row in rows}
    if actual_ids != set(expected_ids):
        raise RuntimeError(
            f"{split} membership mismatch: returned {len(actual_ids)} matches, "
            f"expected {len(expected_ids)} locked matches"
        )
    shot_ids = [row.shot_id for row in rows]
    if len(shot_ids) != len(set(shot_ids)):
        raise RuntimeError(f"{split} contains duplicate shot ids")
    if expected_shots is not None and len(rows) != expected_shots:
        raise RuntimeError(f"{split} has {len(rows)} rows, expected {expected_shots}")
    if expected_matches is not None and len(actual_ids) != expected_matches:
        raise RuntimeError(f"{split} has {len(actual_ids)} matches, expected {expected_matches}")


def _calibration_decision_payload(
    frozen: FrozenBaseModel,
    rows: Sequence[ShotRow],
    adoption: dict[str, object],
    slope: float,
    intercept: float,
    config: PhaseConfig,
    execution_provenance: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "rule_version": CALIBRATION_RULE_VERSION,
        "calibrator": "platt_sigmoid",
        "calibration_split": "WC2022",
        "calibration_fit_scope": "WC2022_only",
        "holdout_accessed": False,
        "base_identity": frozen.identity.as_dict(),
        "registered_base": BaseModelPins.from_mapping(
            cast(Mapping[str, object], config.value("frozen_base"))
        ).as_dict(),
        "calibration_config_path": record_path(config.path),
        "calibration_config_sha256": config.sha256,
        "execution_provenance": dict(execution_provenance),
        "execution_provenance_sha256": exact_payload_sha256(execution_provenance),
        "platt_slope": slope,
        "platt_intercept": intercept,
        "platt_parameter_sha256": platt_parameter_digest(slope, intercept),
        "calibration_membership": {
            "n_rows": len(rows),
            "n_matches": len({row.match_id for row in rows}),
            "membership_sha256": membership_digest(rows),
        },
        "adoption": adoption,
        "adopted_variant": adoption["adopted_variant"],
        "raw_anchor_reliability": adoption["raw_anchor_reliability"],
        "raw_variant_reliability": adoption["raw_variant_reliability"],
        "calibrated_variant_reliability": adoption["calibrated_variant_reliability"],
    }


def run_calibration_phase(
    *,
    config_path: str | Path = DEFAULT_CALIBRATION_CONFIG_PATH,
    calibration_loader: Callable[[], Sequence[ShotRow]] | None = None,
    db_url: str | None = None,
    expected_shots: int | None = CALIBRATION_EXPECTED_SHOTS,
    expected_matches: int | None = CALIBRATION_EXPECTED_MATCHES,
) -> CalibrationDecision:
    """Verify registered locks, then fit only Platt parameters on WC2022."""
    config = _load_phase_config(
        config_path, "calibration", enforce_registered=calibration_loader is None
    )
    execution_provenance = _resolve_execution_provenance(config)
    pins = BaseModelPins.from_mapping(cast(Mapping[str, object], config.value("frozen_base")))
    frozen = freeze_base_model(pins)
    sql, assignments = _load_locked_inputs(config, pins)
    if calibration_loader is None:
        if db_url is None:
            raise RuntimeError("calibration phase needs the configured read-only database URL")
        with open_db(db_url) as connection:
            rows = load_partition_cohort(connection, sql, assignments, "calibration")
    else:
        rows = list(calibration_loader())
    _assert_partition_anchor(
        rows,
        assignments,
        "calibration",
        expected_shots=expected_shots,
        expected_matches=expected_matches,
    )
    logits = frozen.predict_logits(rows)
    raw = np.asarray(expit(logits), dtype=np.float64)
    y = np.asarray([row.y for row in rows], dtype=np.int_)
    calibrator = fit_platt(logits, y)
    calibrated = calibrator.predict(logits)
    adoption = decide_calibration_adoption(
        y,
        raw,
        calibrated,
        platt_slope=calibrator.slope,
        platt_intercept=calibrator.intercept,
    )
    assert_frozen_base_unchanged(frozen)
    payload = _calibration_decision_payload(
        frozen,
        rows,
        adoption,
        calibrator.slope,
        calibrator.intercept,
        config,
        execution_provenance,
    )
    decision = write_calibration_decision(config.path_value("decision_path"), payload)
    return decision


def run_holdout_phase(
    *,
    config_path: str | Path = DEFAULT_HOLDOUT_CONFIG_PATH,
    holdout_loader: Callable[[], Sequence[ShotRow]] | None = None,
    db_url: str | None = None,
    run_id: str | None = None,
    expected_decision_sha256: str | None = None,
    expected_shots: int | None = HOLDOUT_EXPECTED_SHOTS,
    expected_matches: int | None = HOLDOUT_EXPECTED_MATCHES,
) -> HoldoutAccessAudit:
    """Open Euro2024 once and complete every row-derived stage in this one call."""
    real_execution = holdout_loader is None
    config = _load_phase_config(config_path, "holdout", enforce_registered=real_execution)
    calibration_config_path = config.path_value("calibration_config_path")
    calibration_config = _load_phase_config(
        calibration_config_path, "calibration", enforce_registered=real_execution
    )
    if calibration_config.sha256 != config.text("calibration_config_sha256"):
        raise RuntimeError("holdout config does not reference the exact frozen calibration config")
    if expected_decision_sha256 is None or len(expected_decision_sha256) != 64:
        raise RuntimeError("holdout phase requires the exact calibration-decision SHA-256")
    try:
        int(expected_decision_sha256, 16)
    except ValueError as exc:
        raise RuntimeError(
            "holdout phase requires a hexadecimal calibration-decision SHA-256"
        ) from exc
    execution_provenance = _resolve_execution_provenance(config)
    pins = BaseModelPins.from_mapping(
        cast(Mapping[str, object], calibration_config.value("frozen_base"))
    )
    frozen = freeze_base_model(pins)
    decision = load_calibration_decision(config.path_value("required_calibration_decision"))
    if decision.decision_sha256 != expected_decision_sha256:
        raise RuntimeError("calibration-decision SHA-256 does not match the frozen request")
    verify_calibration_decision(decision, frozen)
    if decision.payload.get("calibration_config_sha256") != calibration_config.sha256:
        raise RuntimeError(
            "calibration decision was not produced by the registered calibration config"
        )
    _assert_decision_execution_matches(decision, execution_provenance)
    sql, assignments = _load_locked_inputs(calibration_config, pins)
    output_dir = config.path_value("output_dir")
    holdout_outputs = (
        output_dir / "holdout-access-audit.json",
        output_dir / "holdout-metrics.json",
        output_dir / "evidence.md",
        output_dir / "model-card.md",
        output_dir / "plots/reliability.svg",
        output_dir / "plots/slices.svg",
    )
    existing_outputs = [record_path(path) for path in holdout_outputs if path.exists()]
    if existing_outputs:
        raise RuntimeError(
            "refusing to reopen a holdout with existing row-derived evidence: "
            + ", ".join(existing_outputs)
        )

    connection = None
    if holdout_loader is None:
        if db_url is None:
            raise RuntimeError("holdout phase needs the configured read-only database URL")
        connection = open_db(db_url)

        def loader() -> Sequence[ShotRow]:
            return load_partition_cohort(connection, sql, assignments, "holdout")

    else:
        loader = holdout_loader

    evidence_audit: HoldoutAccessAudit | None = None
    result: dict[str, object] | None = None
    session = HoldoutAccessSession(loader)
    try:
        rows = list(session.open())
        _assert_partition_anchor(
            rows,
            assignments,
            "holdout",
            expected_shots=expected_shots,
            expected_matches=expected_matches,
        )
        goals = sum(row.y for row in rows)
        audit = HoldoutAccessAudit(
            run_id=run_id or datetime.now(UTC).strftime("wp2-7-%Y%m%dT%H%M%SZ"),
            decision_sha256=decision.decision_sha256,
            holdout_open_count=1,
            membership_sha256=membership_digest(rows),
            n_rows=len(rows),
            n_matches=len({row.match_id for row in rows}),
            n_goals=goals,
            n_misses=len(rows) - goals,
            execution_provenance_sha256=exact_payload_sha256(execution_provenance),
            stages=("holdout_open", "membership_asserted"),
        )
        result = evaluate_holdout_rows(rows, frozen, decision)
        audit = replace(
            audit,
            stages=("holdout_open", "membership_asserted", "scored", "bootstrap", "slices"),
        )
        evidence_audit = write_holdout_evidence(
            output_dir,
            result,
            audit,
            published_report_path=config.path_value("published_evidence_report"),
            published_model_card_path=config.path_value("published_model_card"),
        )
    finally:
        if connection is not None:
            connection.close()
    if evidence_audit is None or result is None:
        raise RuntimeError("WP2.7 holdout exited without complete evidence")
    closed_audit = replace(evidence_audit, stages=(*evidence_audit.stages, "holdout_closed"))
    final_audit = finalize_holdout_audit(
        output_dir,
        result,
        closed_audit,
        experiment_record_path=config.path_value("experiment_record_path"),
        execution_provenance=execution_provenance,
        experiment_id=config.text("experiment_id"),
    )
    if final_audit.stages != EXPECTED_HOLDOUT_STAGES:
        raise RuntimeError("WP2.7 holdout did not complete its ordered stage ledger")
    return final_audit


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="touchline.modeling.wp2_7")
    subparsers = parser.add_subparsers(dest="phase", required=True)
    subparsers.add_parser("calibrate")
    holdout = subparsers.add_parser("holdout")
    holdout.add_argument("--decision-sha256", required=True)
    holdout.add_argument("--run-id")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    db_url = os.environ.get(DEFAULT_DB_URL_ENV)
    if args.phase == "calibrate":
        run_calibration_phase(db_url=db_url)
        return 0
    run_holdout_phase(
        db_url=db_url,
        run_id=args.run_id,
        expected_decision_sha256=args.decision_sha256,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
