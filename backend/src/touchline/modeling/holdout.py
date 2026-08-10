"""WP2.7 holdout evaluation primitives and the supervised one-open session.

The functions here accept already-materialized rows.  The real Euro2024 loader is owned by the
phase runner, which creates exactly one :class:`HoldoutAccessSession` and keeps every assertion,
score, bootstrap, slice, and evidence write inside that invocation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TypeVar, cast

import numpy as np
import numpy.typing as npt
from scipy.special import expit  # type: ignore[import-untyped]

from touchline.modeling.calibration import (
    CalibrationContractError,
    CalibrationDecision,
    FrozenBaseModel,
    PlattCalibrator,
    assert_frozen_base_unchanged,
    exact_json_bytes,
    verify_calibration_decision,
)
from touchline.modeling.experiment import abs_path, record_path
from touchline.modeling.metrics import (
    SingleClassFoldError,
    brier_score,
    canonical_metrics_json,
    log_loss,
    pr_auc,
    reliability_table,
    roc_auc,
)
from touchline.modeling.preprocessing import ShotRow

__all__ = [
    "ANGLE_BANDS_RADIANS",
    "BOOTSTRAP_CONFIDENCE_LEVEL",
    "BOOTSTRAP_REPLICATES",
    "BOOTSTRAP_SEED",
    "DISTANCE_BANDS_STATSBOMB_UNITS",
    "EXPECTED_HOLDOUT_STAGES",
    "SLICE_MIN_GOALS",
    "SLICE_MIN_MATCHES",
    "SLICE_MIN_MISSES",
    "SLICE_MIN_SHOTS",
    "HoldoutAccessAudit",
    "HoldoutAccessError",
    "HoldoutAccessSession",
    "evaluate_holdout_rows",
    "finalize_holdout_audit",
    "membership_digest",
    "paired_match_bootstrap",
    "verify_holdout_audit_metadata",
    "write_holdout_evidence",
]

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int_]
RowT = TypeVar("RowT")

BOOTSTRAP_REPLICATES = 2_000
BOOTSTRAP_SEED = 0
BOOTSTRAP_CONFIDENCE_LEVEL = 0.95
SLICE_MIN_SHOTS = 50
SLICE_MIN_GOALS = 5
SLICE_MIN_MISSES = 5
SLICE_MIN_MATCHES = 10

# Human-facing labels explicitly use StatsBomb coordinate units.  They are not yards/metres.
DISTANCE_BANDS_STATSBOMB_UNITS: tuple[tuple[str, float, float | None], ...] = (
    ("[0,10)", 0.0, 10.0),
    ("[10,20)", 10.0, 20.0),
    ("[20,30)", 20.0, 30.0),
    ("[30,+inf)", 30.0, None),
)
ANGLE_BANDS_RADIANS: tuple[tuple[str, float, float | None], ...] = (
    ("[0,0.2)", 0.0, 0.2),
    ("[0.2,0.4)", 0.2, 0.4),
    ("[0.4,0.6)", 0.4, 0.6),
    ("[0.6,+inf)", 0.6, None),
)
EXPECTED_HOLDOUT_STAGES = (
    "holdout_open",
    "membership_asserted",
    "scored",
    "bootstrap",
    "slices",
    "evidence_written",
    "holdout_closed",
    "experiment_record_written",
    "audit_finalized",
)


class HoldoutAccessError(RuntimeError):
    """The supervised holdout access boundary was violated."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_digest(payload: Mapping[str, object]) -> str:
    return _sha256(canonical_metrics_json(payload))


def _as_arrays(rows: Sequence[ShotRow]) -> tuple[IntArray, np.ndarray]:
    y = np.asarray([row.y for row in rows], dtype=np.int_)
    if y.ndim != 1 or y.size == 0:
        raise HoldoutAccessError("holdout must contain at least one row")
    return y, np.asarray([row.match_id for row in rows], dtype=np.int_)


def membership_digest(rows: Sequence[ShotRow]) -> str:
    """Hash sorted membership metadata without recording row-level data in evidence."""
    members = sorted((str(row.shot_id), int(row.match_id)) for row in rows)
    return _json_digest({"members": members})


@dataclass(frozen=True)
class HoldoutAccessAudit:
    run_id: str
    decision_sha256: str
    holdout_open_count: int
    membership_sha256: str
    n_rows: int
    n_matches: int
    n_goals: int
    n_misses: int
    execution_provenance_sha256: str
    stages: tuple[str, ...]
    evidence_files_sha256: Mapping[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 2,
            "phase": "wp2-7-holdout",
            "run_id": self.run_id,
            "decision_sha256": self.decision_sha256,
            "holdout_open_count": self.holdout_open_count,
            "membership_sha256": self.membership_sha256,
            "n_rows": self.n_rows,
            "n_matches": self.n_matches,
            "n_goals": self.n_goals,
            "n_misses": self.n_misses,
            "execution_provenance_sha256": self.execution_provenance_sha256,
            "stages": list(self.stages),
            "evidence_files_sha256": dict(sorted(self.evidence_files_sha256.items())),
        }


class HoldoutAccessSession[RowT]:
    """A single-use logical holdout materialization boundary."""

    def __init__(self, loader: Callable[[], Sequence[RowT]]) -> None:
        self._loader = loader
        self._opened = False
        self._rows: tuple[RowT, ...] | None = None

    def open(self) -> tuple[RowT, ...]:
        if self._opened:
            raise HoldoutAccessError(
                "Euro2024 holdout has already been opened in this supervised execution"
            )
        self._opened = True
        self._rows = tuple(self._loader())
        return self._rows


def _score_variant(y: IntArray, probabilities: FloatArray) -> dict[str, object]:
    result: dict[str, object] = {
        "n": int(y.size),
        "positive_count": int(y.sum()),
        "prevalence": float(y.mean()),
        "log_loss": log_loss(y, probabilities),
        "brier": brier_score(y, probabilities),
        "reliability": reliability_table(y, probabilities),
    }
    try:
        result["roc_auc"] = roc_auc(y, probabilities)
        result["pr_auc"] = pr_auc(y, probabilities)
    except SingleClassFoldError:
        result["roc_auc"] = None
        result["pr_auc"] = None
    return result


def _bootstrap_interval(values: np.ndarray) -> dict[str, float]:
    alpha = (1.0 - BOOTSTRAP_CONFIDENCE_LEVEL) / 2.0
    return {
        "lower": float(np.quantile(values, alpha)),
        "upper": float(np.quantile(values, 1.0 - alpha)),
    }


def paired_match_bootstrap(
    rows: Sequence[ShotRow],
    raw: Sequence[float] | FloatArray,
    calibrated: Sequence[float] | FloatArray,
    *,
    repetitions: int = BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, object]:
    """Apply the paired match bootstrap.

    The supervised WP2.7 runner always uses the registered 2,000-replicate/seed-0 values.  The
    explicit parameters are retained only for bounded synthetic tests, which must never open a
    real holdout.
    """
    if repetitions <= 0 or seed < 0:
        raise HoldoutAccessError(
            "bootstrap repetitions must be positive and seed must be nonnegative"
        )
    y, match_ids = _as_arrays(rows)
    raw_values = np.asarray(raw, dtype=np.float64)
    calibrated_values = np.asarray(calibrated, dtype=np.float64)
    if raw_values.shape != calibrated_values.shape or raw_values.shape != y.shape:
        raise HoldoutAccessError("bootstrap variants must have identical row membership")
    groups: dict[int, np.ndarray] = {}
    for match_id in sorted(set(int(value) for value in match_ids)):
        groups[match_id] = np.flatnonzero(match_ids == match_id)
    match_keys = np.asarray(sorted(groups), dtype=np.int_)
    rng = np.random.default_rng(seed)
    raw_ll: list[float] = []
    calibrated_ll: list[float] = []
    raw_brier: list[float] = []
    calibrated_brier: list[float] = []
    for _ in range(repetitions):
        sampled_matches = rng.choice(match_keys, size=match_keys.size, replace=True)
        sampled_indices = np.concatenate([groups[int(match)] for match in sampled_matches])
        y_sample = y[sampled_indices]
        raw_sample = raw_values[sampled_indices]
        calibrated_sample = calibrated_values[sampled_indices]
        raw_ll.append(log_loss(y_sample, raw_sample))
        calibrated_ll.append(log_loss(y_sample, calibrated_sample))
        raw_brier.append(brier_score(y_sample, raw_sample))
        calibrated_brier.append(brier_score(y_sample, calibrated_sample))
    raw_ll_array = np.asarray(raw_ll)
    calibrated_ll_array = np.asarray(calibrated_ll)
    raw_brier_array = np.asarray(raw_brier)
    calibrated_brier_array = np.asarray(calibrated_brier)
    return {
        "repetitions": repetitions,
        "seed": seed,
        "confidence_level": BOOTSTRAP_CONFIDENCE_LEVEL,
        "raw": {
            "log_loss": _bootstrap_interval(raw_ll_array),
            "brier": _bootstrap_interval(raw_brier_array),
        },
        "calibrated": {
            "log_loss": _bootstrap_interval(calibrated_ll_array),
            "brier": _bootstrap_interval(calibrated_brier_array),
        },
        "effect_calibrated_minus_raw": {
            "log_loss": _bootstrap_interval(calibrated_ll_array - raw_ll_array),
            "brier": _bootstrap_interval(calibrated_brier_array - raw_brier_array),
        },
    }


def _categorical_level(row: ShotRow, family: str) -> str:
    return str(getattr(row, family))


def _numeric_level(value: float, bands: Sequence[tuple[str, float, float | None]]) -> str:
    for label, lower, upper in bands:
        if value >= lower and (upper is None or value < upper):
            return label
    raise HoldoutAccessError(f"value {value} does not fit a pre-registered slice band")


def _slice_levels(row: ShotRow) -> dict[str, str]:
    return {
        "body_part_name": _categorical_level(row, "body_part_name"),
        "technique_name": _categorical_level(row, "technique_name"),
        "play_pattern_name": _categorical_level(row, "play_pattern_name"),
        "shot_type_name": _categorical_level(row, "shot_type_name"),
        "distance_statsbomb_coordinate_units": _numeric_level(
            row.distance_to_goal, DISTANCE_BANDS_STATSBOMB_UNITS
        ),
        "visible_goal_angle_radians": _numeric_level(row.visible_goal_angle, ANGLE_BANDS_RADIANS),
    }


def _slice_results(
    rows: Sequence[ShotRow], raw: FloatArray, calibrated: FloatArray
) -> dict[str, list[dict[str, object]]]:
    y = np.asarray([row.y for row in rows], dtype=np.int_)
    level_maps = [_slice_levels(row) for row in rows]
    output: dict[str, list[dict[str, object]]] = {}
    for family in level_maps[0]:
        levels = sorted({mapping[family] for mapping in level_maps})
        family_rows: list[dict[str, object]] = []
        for level in levels:
            mask = np.asarray([mapping[family] == level for mapping in level_maps], dtype=bool)
            count = int(mask.sum())
            positives = int(y[mask].sum())
            misses = count - positives
            matches = len({rows[index].match_id for index, included in enumerate(mask) if included})
            supported = (
                count >= SLICE_MIN_SHOTS
                and positives >= SLICE_MIN_GOALS
                and misses >= SLICE_MIN_MISSES
                and matches >= SLICE_MIN_MATCHES
            )
            entry: dict[str, object] = {
                "level": level,
                "status": "supported" if supported else "sparse",
                "n": count,
                "positive_count": positives,
                "negative_count": misses,
                "n_matches": matches,
            }
            if supported:
                entry["raw"] = _score_variant(y[mask], raw[mask])
                entry["calibrated"] = _score_variant(y[mask], calibrated[mask])
            family_rows.append(entry)
        output[family] = family_rows
    return output


def evaluate_holdout_rows(
    rows: Sequence[ShotRow],
    frozen: FrozenBaseModel,
    decision: CalibrationDecision,
    *,
    bootstrap_repetitions: int = BOOTSTRAP_REPLICATES,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> dict[str, object]:
    """Score the frozen raw/calibrated pair; no candidate selection occurs here."""
    verify_calibration_decision(decision, frozen)
    rows_list = list(rows)
    if not rows_list:
        raise HoldoutAccessError("holdout evaluation received no rows")
    shot_ids = [row.shot_id for row in rows_list]
    if len(shot_ids) != len(set(shot_ids)):
        raise HoldoutAccessError("holdout membership contains duplicate shot ids")
    y, _match_ids = _as_arrays(rows_list)
    logits = frozen.predict_logits(rows_list)
    raw = np.asarray(expit(logits), dtype=np.float64)
    try:
        slope = float(cast(float, decision.payload["platt_slope"]))
        intercept = float(cast(float, decision.payload["platt_intercept"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise CalibrationContractError("calibration decision has no Platt parameters") from exc
    calibrated = PlattCalibrator(slope, intercept).predict(logits)
    assert_frozen_base_unchanged(frozen)
    result: dict[str, object] = {
        "schema_version": 1,
        "candidate": "full_minus_presence",
        "adopted_variant": decision.adopted_variant,
        "decision_sha256": decision.decision_sha256,
        "n_rows": int(y.size),
        "n_matches": len({row.match_id for row in rows_list}),
        "observed_prevalence": float(y.mean()),
        "variants": {
            "raw": _score_variant(y, raw),
            "calibrated": _score_variant(y, calibrated),
        },
        "raw_anchor_reliability": decision.payload.get("raw_anchor_reliability"),
        "holdout_raw_vs_calibrated_effect": {
            "log_loss": float(log_loss(y, calibrated) - log_loss(y, raw)),
            "brier": float(brier_score(y, calibrated) - brier_score(y, raw)),
        },
        "bootstrap": paired_match_bootstrap(
            rows_list,
            raw,
            calibrated,
            repetitions=bootstrap_repetitions,
            seed=bootstrap_seed,
        ),
        "slices": _slice_results(rows_list, raw, calibrated),
    }
    return result


def _reliability_svg(result: Mapping[str, object]) -> str:
    variants = cast(Mapping[str, Mapping[str, object]], result["variants"])
    width, height = 720, 420
    left, bottom, plot_width, plot_height = 70, 50, 600, 320
    lines = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}">'
        ),
        '<rect width="100%" height="100%" fill="white"/>',
        (
            f'<line x1="{left}" y1="{bottom}" x2="{left + plot_width}" '
            f'y2="{bottom}" stroke="black"/>'
        ),
        (
            f'<line x1="{left}" y1="{bottom}" x2="{left}" '
            f'y2="{bottom + plot_height}" stroke="black"/>'
        ),
        (
            f'<line x1="{left}" y1="{bottom + plot_height}" '
            f'x2="{left + plot_width}" y2="{bottom}" '
            'stroke="#bbb" stroke-dasharray="4 4"/>'
        ),
        (
            '<text x="70" y="25" font-family="sans-serif" font-size="16">'
            "WP2.7 holdout reliability</text>"
        ),
        ('<text x="280" y="410" font-family="sans-serif" font-size="12">mean prediction</text>'),
        (
            '<text x="10" y="220" transform="rotate(-90 10 220)" '
            'font-family="sans-serif" font-size="12">observed rate</text>'
        ),
    ]
    colors = {"raw": "#1f77b4", "calibrated": "#d62728"}
    for variant, color in colors.items():
        table = cast(Sequence[Mapping[str, object]], variants[variant]["reliability"])
        points: list[str] = []
        for entry in table:
            mean = entry["mean_prediction"]
            observed = entry["observed_rate"]
            if mean is None or observed is None:
                continue
            x = left + float(cast(float, mean)) * plot_width
            y = bottom + plot_height - float(cast(float, observed)) * plot_height
            points.append(f"{x:.3f},{y:.3f}")
        if points:
            points_text = " ".join(points)
            lines.append(
                f'<polyline points="{points_text}" fill="none" stroke="{color}" stroke-width="3"/>'
            )
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def _slice_svg(result: Mapping[str, object]) -> str:
    slices = cast(Mapping[str, Sequence[Mapping[str, object]]], result["slices"])
    supported = sum(
        1 for entries in slices.values() for entry in entries if entry.get("status") == "supported"
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="720" height="260" '
        'viewBox="0 0 720 260">\n'
        '<rect width="100%" height="100%" fill="white"/>\n'
        '<text x="40" y="45" font-family="sans-serif" font-size="16">'
        "WP2.7 slice coverage</text>\n"
        f'<text x="40" y="95" font-family="sans-serif" font-size="14">'
        f"Supported slice levels: {supported}</text>\n"
        '<text x="40" y="135" font-family="sans-serif" font-size="12">'
        "Sparse levels remain listed and are not interpreted.</text>\n"
        "</svg>\n"
    )


def _evidence_markdown(result: Mapping[str, object]) -> str:
    variants = cast(Mapping[str, Mapping[str, object]], result["variants"])
    goals = int(cast(int, variants["raw"]["positive_count"]))
    rows = int(cast(int, result["n_rows"]))
    lines = [
        "# WP2.7 calibration and holdout evidence",
        "",
        (
            "The holdout packet evaluates only the selected `full_minus_presence` logistic "
            "model in raw and calibrated forms."
        ),
        "The constant baseline is absent; observed prevalence is descriptive context only.",
        "",
        f"- Adopted variant (frozen before holdout): `{result['adopted_variant']}`",
        f"- Rows: {result['n_rows']}",
        f"- Matches: {result['n_matches']}",
        f"- Goals: {goals}",
        f"- Misses: {rows - goals}",
        f"- Observed prevalence: {float(cast(float, result['observed_prevalence'])):.12f}",
        "",
        "| Variant | Log loss | Brier |",
        "|---|---:|---:|",
    ]
    for variant in ("raw", "calibrated"):
        metrics = variants[variant]
        lines.append(
            f"| {variant} | {float(cast(float, metrics['log_loss'])):.12f} | "
            f"{float(cast(float, metrics['brier'])):.12f} |"
        )
    lines.extend(
        [
            "",
            (
                "All real holdout assertions, scoring, bootstrap, slices, and evidence "
                "generation were performed inside the single supervised `wp2-7-holdout` "
                "execution."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _model_card(result: Mapping[str, object]) -> str:
    return (
        "# Shot-quality model card — WP2.7\n\n"
        "## Intended use\n\n"
        "A selected-logistic shot-conversion probability for research and analyst "
        "decision support; "
        "Platt calibration is adopted only when the frozen WC2022 rule passes. It is not "
        "StatsBomb's "
        "xG model.\n\n"
        "## Model and data\n\n"
        "The base estimator is the selected `full_minus_presence` regularized logistic model "
        "fitted on WC2018 + Euro2020 only. Platt parameters are fitted on WC2022 only. "
        "Euro2024 is a tournament holdout. Registered artifact and current execution identities "
        "are verified before access.\n\n"
        "## Holdout result\n\n"
        f"The pre-holdout adopted variant was `{result['adopted_variant']}`. The holdout "
        "reports raw and calibrated effects without selecting between them.\n\n"
        "Distance is expressed in StatsBomb coordinate units; visible goal angle is in radians. "
        "The paired match bootstrap uses 2,000 replicates and seed 0. Sparse slice levels are not "
        "interpreted.\n"
    )


def write_holdout_evidence(
    output_dir: str | Path,
    result: Mapping[str, object],
    audit: HoldoutAccessAudit,
    *,
    published_report_path: str | Path,
    published_model_card_path: str | Path,
) -> HoldoutAccessAudit:
    """Write row-derived evidence, leaving closure/audit finalization to the runner."""
    expected_input_stages = (
        "holdout_open",
        "membership_asserted",
        "scored",
        "bootstrap",
        "slices",
    )
    if audit.stages != expected_input_stages:
        raise HoldoutAccessError("holdout evidence was requested from an invalid stage ledger")
    output = Path(output_dir)
    plots = output / "plots"
    plots.mkdir(parents=True, exist_ok=True)
    metrics_path = output / "holdout-metrics.json"
    report_path = output / "evidence.md"
    model_card_path = output / "model-card.md"
    reliability_path = plots / "reliability.svg"
    slices_path = plots / "slices.svg"
    report_text = _evidence_markdown(result)
    model_card_text = _model_card(result)
    metrics_path.write_bytes(canonical_metrics_json(dict(result)))
    report_path.write_text(report_text, encoding="utf-8")
    model_card_path.write_text(model_card_text, encoding="utf-8")
    reliability_path.write_text(_reliability_svg(result), encoding="utf-8")
    slices_path.write_text(_slice_svg(result), encoding="utf-8")
    published_report = Path(published_report_path)
    published_model_card = Path(published_model_card_path)
    published_report.parent.mkdir(parents=True, exist_ok=True)
    published_model_card.parent.mkdir(parents=True, exist_ok=True)
    published_report.write_text(report_text, encoding="utf-8")
    published_model_card.write_text(model_card_text, encoding="utf-8")
    evidence_files = (
        metrics_path,
        report_path,
        model_card_path,
        reliability_path,
        slices_path,
        published_report,
        published_model_card,
    )
    evidence_hashes = {record_path(path): _sha256(path.read_bytes()) for path in evidence_files}
    return replace(
        audit,
        evidence_files_sha256=evidence_hashes,
        stages=(*audit.stages, "evidence_written"),
    )


def finalize_holdout_audit(
    output_dir: str | Path,
    result: Mapping[str, object],
    audit: HoldoutAccessAudit,
    *,
    experiment_record_path: str | Path,
    execution_provenance: Mapping[str, object],
    experiment_id: str,
) -> HoldoutAccessAudit:
    """Finalize metadata only after the runner has closed the holdout connection/session."""
    expected_stages = (
        "holdout_open",
        "membership_asserted",
        "scored",
        "bootstrap",
        "slices",
        "evidence_written",
        "holdout_closed",
    )
    if audit.stages != expected_stages:
        raise HoldoutAccessError("holdout audit cannot finalize before holdout_closed")
    output = Path(output_dir)
    record_path_value = Path(experiment_record_path)
    record_path_value.parent.mkdir(parents=True, exist_ok=True)
    experiment_record: dict[str, object] = {
        "schema_version": 2,
        "experiment_id": experiment_id,
        "work_package": "WP2.7",
        "status": "holdout_complete_pending_independent_review",
        "base_candidate": result["candidate"],
        "adopted_variant": result["adopted_variant"],
        "decision_sha256": audit.decision_sha256,
        "holdout_membership_sha256": audit.membership_sha256,
        "aggregate_counts": {
            "rows": audit.n_rows,
            "matches": audit.n_matches,
            "goals": audit.n_goals,
            "misses": audit.n_misses,
        },
        "execution_provenance": dict(execution_provenance),
        "evidence_files_sha256": dict(sorted(audit.evidence_files_sha256.items())),
        "real_rows_accessed_in_this_recording": True,
        "review_status": "pending_independent_sol_reviewer",
    }
    record_path_value.write_bytes(exact_json_bytes(experiment_record))
    evidence_hashes = dict(audit.evidence_files_sha256)
    evidence_hashes[record_path(record_path_value)] = _sha256(record_path_value.read_bytes())
    final_audit = replace(
        audit,
        evidence_files_sha256=evidence_hashes,
        stages=(*audit.stages, "experiment_record_written", "audit_finalized"),
    )
    if final_audit.stages != EXPECTED_HOLDOUT_STAGES:
        raise HoldoutAccessError("holdout audit stages are incomplete or out of order")
    output.mkdir(parents=True, exist_ok=True)
    (output / "holdout-access-audit.json").write_bytes(exact_json_bytes(final_audit.as_dict()))
    return final_audit


def verify_holdout_audit_metadata(path: str | Path) -> dict[str, object]:
    """Validate only the audit envelope; this function never opens a database or rows."""
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HoldoutAccessError(f"cannot read holdout audit metadata {source}") from exc
    if not isinstance(payload, dict):
        raise HoldoutAccessError("holdout audit metadata must be a JSON object")
    if payload.get("schema_version") != 2 or payload.get("phase") != "wp2-7-holdout":
        raise HoldoutAccessError("holdout audit phase is not wp2-7-holdout")
    if payload.get("holdout_open_count") != 1:
        raise HoldoutAccessError("holdout audit does not record exactly one logical open")
    if tuple(payload.get("stages", ())) != EXPECTED_HOLDOUT_STAGES:
        raise HoldoutAccessError("holdout audit stages are incomplete or out of order")
    n_goals = payload.get("n_goals")
    n_misses = payload.get("n_misses")
    n_rows = payload.get("n_rows")
    if (
        not isinstance(n_goals, int)
        or not isinstance(n_misses, int)
        or not isinstance(n_rows, int)
        or n_goals + n_misses != n_rows
    ):
        raise HoldoutAccessError("holdout audit goal/miss counts do not reconcile to row count")
    for key in ("decision_sha256", "membership_sha256", "execution_provenance_sha256"):
        if not isinstance(payload.get(key), str) or len(str(payload[key])) != 64:
            raise HoldoutAccessError(f"holdout audit {key} is missing or malformed")
    evidence = payload.get("evidence_files_sha256")
    if not isinstance(evidence, dict) or not evidence:
        raise HoldoutAccessError("holdout audit has no per-file evidence hashes")
    for recorded_path, expected in evidence.items():
        if (
            not isinstance(recorded_path, str)
            or not isinstance(expected, str)
            or len(expected) != 64
        ):
            raise HoldoutAccessError("holdout audit contains malformed per-file evidence metadata")
        evidence_path = abs_path(recorded_path)
        if not evidence_path.is_file() or _sha256(evidence_path.read_bytes()) != expected:
            raise HoldoutAccessError(f"holdout evidence hash mismatch for {recorded_path}")
    return payload
