"""Synthetic and metadata-only contracts for the WP2.7 calibration phase."""

from __future__ import annotations

import json
import pickle
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Literal, cast

import numpy as np
import pytest
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]

import touchline.modeling.wp2_7 as wp2_7
from touchline.modeling.artifact import ArtifactBundle, artifact_schema_version
from touchline.modeling.calibration import (
    ADOPTION_TOLERANCE,
    CALIBRATION_RULE_VERSION,
    D11_MIN_SUPPORT,
    BaseModelIdentity,
    BaseModelPins,
    CalibrationContractError,
    CalibrationDecision,
    CalibrationDecisionError,
    assert_frozen_base_unchanged,
    decide_calibration_adoption,
    exact_payload_sha256,
    freeze_base_model,
    load_calibration_decision,
    paired_raw_anchor_reliability,
    platt_parameter_digest,
    write_calibration_decision,
)
from touchline.modeling.dataset import parse_match_assignments
from touchline.modeling.holdout import (
    HoldoutAccessAudit,
    HoldoutAccessError,
    HoldoutAccessSession,
    evaluate_holdout_rows,
    finalize_holdout_audit,
    verify_holdout_audit_metadata,
)
from touchline.modeling.preprocessing import REFERENCE_LEVELS, ShotRow, StandardScaler, Vocabulary
from touchline.modeling.wp2_7 import run_calibration_phase, run_holdout_phase

ROOT = Path(__file__).resolve().parents[2]


class FitForbiddenLogisticRegression(LogisticRegression):  # type: ignore[misc]
    """A fitted synthetic base whose fit method makes any phase refit observable."""

    def fit(self, *args: object, **kwargs: object) -> FitForbiddenLogisticRegression:
        raise AssertionError("the frozen base estimator must never be fitted by WP2.7")


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _synthetic_base(
    tmp_path: Path,
    *,
    cohort_sql_sha256: str = "2" * 64,
    assignments_sha256: str = "3" * 64,
) -> tuple[BaseModelPins, list[ShotRow]]:
    rows = [
        ShotRow(
            shot_id=f"synthetic-base-{index}",
            match_id=1,
            fold=0,
            competition_id=43,
            season_id=3,
            y=index % 2,
            distance_to_goal=5.0 + index,
            visible_goal_angle=0.1 + index / 100.0,
            body_part_name="Right Foot",
            technique_name="Normal",
            play_pattern_name="Regular Play",
            first_time=None,
            under_pressure=None,
            shot_type_name="Open Play",
        )
        for index in range(20)
    ]
    scaler = StandardScaler(
        mean={"distance_to_goal": 14.5, "visible_goal_angle": 0.195},
        std={"distance_to_goal": 5.766281297335398, "visible_goal_angle": 0.05766281297335398},
    )
    vocabulary = Vocabulary(
        levels={field: () for field in REFERENCE_LEVELS},
        reference=dict(REFERENCE_LEVELS),
        rare_members={field: () for field in REFERENCE_LEVELS},
    )
    design = np.column_stack(
        [
            [(row.distance_to_goal - 14.5) / 5.766281297335398 for row in rows],
            [(row.visible_goal_angle - 0.195) / 0.05766281297335398 for row in rows],
        ]
    )
    estimator = FitForbiddenLogisticRegression(C=0.1, solver="lbfgs", max_iter=1_000)
    LogisticRegression.fit(estimator, design, np.asarray([row.y for row in rows]))
    digest = "1" * 64
    bundle = ArtifactBundle(
        schema_version=artifact_schema_version,
        experiment_id="synthetic-wp2-4-base",
        shipped_candidate="full_minus_presence",
        best_c=0.1,
        code_commit="synthetic-base-code",
        reproduction_commit="synthetic-base-code",
        data_source_commit="synthetic-source",
        cohort_sql_sha256=cohort_sql_sha256,
        assignments_sha256=assignments_sha256,
        input_config_sha256=digest,
        uv_lock_sha256="4" * 64,
        estimator=estimator,
        scaler=scaler,
        vocabulary=vocabulary,
        all_columns=(
            "distance_to_goal",
            "visible_goal_angle",
            "first_time_presence",
            "under_pressure_presence",
        ),
        selected_columns=("distance_to_goal", "visible_goal_angle"),
        selected_indices=(0, 1),
        reference_levels=dict(REFERENCE_LEVELS),
        rare_mapping={field: () for field in REFERENCE_LEVELS},
    )
    artifact = tmp_path / "model.pkl"
    artifact.write_bytes(pickle.dumps(bundle, protocol=5))
    base_config = tmp_path / "base-config.json"
    base_config.write_bytes(b"synthetic-base-config\n")
    bundle = replace(bundle, input_config_sha256=_sha(base_config))
    artifact.write_bytes(pickle.dumps(bundle, protocol=5))
    manifest = tmp_path / "artifact-manifest.json"
    manifest_payload = {
        "artifact_schema_version": artifact_schema_version,
        "code_commit": bundle.code_commit,
        "d5_include": False,
        "data_source_commit": bundle.data_source_commit,
        "experiment_id": bundle.experiment_id,
        "input_config_path": base_config.as_posix(),
        "input_config_sha256": bundle.input_config_sha256,
        "model_pickle_path": artifact.as_posix(),
        "model_pickle_sha256": _sha(artifact),
        "reproduction_commit": bundle.reproduction_commit,
        "shipped_best_c": bundle.best_c,
        "shipped_candidate": bundle.shipped_candidate,
        "shipped_feature_columns": list(bundle.selected_columns),
        "shipped_feature_set": "geometry+categoricals",
        "uv_lock_sha256": bundle.uv_lock_sha256,
    }
    manifest.write_text(
        json.dumps(manifest_payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    pins = BaseModelPins(
        artifact_path=artifact.as_posix(),
        artifact_manifest_path=manifest.as_posix(),
        artifact_schema_version=artifact_schema_version,
        model_pickle_sha256=_sha(artifact),
        artifact_manifest_sha256=_sha(manifest),
        experiment_id=bundle.experiment_id,
        candidate=bundle.shipped_candidate,
        shipped_feature_set="geometry+categoricals",
        best_c=bundle.best_c,
        data_source_commit=bundle.data_source_commit,
        cohort_sql_sha256=bundle.cohort_sql_sha256,
        assignments_sha256=bundle.assignments_sha256,
        code_commit=bundle.code_commit,
        reproduction_commit=bundle.reproduction_commit,
        input_config_sha256=bundle.input_config_sha256,
        uv_lock_sha256=bundle.uv_lock_sha256,
    )
    return pins, rows


@dataclass(frozen=True)
class SyntheticWP27:
    calibration_config: Path
    holdout_config: Path
    calibration_rows: tuple[ShotRow, ...]
    holdout_rows: tuple[ShotRow, ...]


def _write_json(path: Path, payload: Mapping[str, object]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return _sha(path)


def _synthetic_wp27(tmp_path: Path) -> SyntheticWP27:
    assignments_path = tmp_path / "assignments.csv"
    assignments_path.write_bytes(
        b"match_id,competition_id,season_id,match_date,split,fold\n"
        b"1,43,3,2018-06-14,development,0\n"
        b"2,43,106,2022-11-20,calibration,\n"
        b"3,55,282,2024-06-14,holdout,\n"
    )
    cohort_sql_path = tmp_path / "cohort.sql"
    cohort_sql_path.write_bytes(b"SELECT 1 AS synthetic_cohort\n")
    assignments_digest = _sha(assignments_path)
    cohort_digest = _sha(cohort_sql_path)
    pins, base_rows = _synthetic_base(
        tmp_path,
        cohort_sql_sha256=cohort_digest,
        assignments_sha256=assignments_digest,
    )
    split_manifest_path = tmp_path / "split-manifest.json"
    split_digest = _write_json(
        split_manifest_path,
        {
            "assignments_sha256": assignments_digest,
            "cohort_sql_sha256": cohort_digest,
            "source_commit": "synthetic-source",
        },
    )
    output = tmp_path / "experiment"
    calibration_config = tmp_path / "calibration-config.json"
    calibration_payload: dict[str, object] = {
        "schema_version": 1,
        "experiment_id": "synthetic-wp27",
        "phase": "calibration",
        "status": "pre_registered_not_run",
        "require_clean_provenance": False,
        "code_commit": "synthetic-current-code",
        "data_source_commit": "synthetic-source",
        "base_fit_scope": "development_only",
        "development_tournaments": ["WC2018", "Euro2020"],
        "calibration_tournament": "WC2022",
        "holdout_tournament": "Euro2024",
        "calibration_rule_version": CALIBRATION_RULE_VERSION,
        "calibrator": "platt_sigmoid",
        "raw_anchor_bin_edges": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
        "minimum_supported_bin_shots": 100,
        "adoption_tolerance": ADOPTION_TOLERANCE,
        "frozen_base": pins.as_dict(),
        "assignments_path": assignments_path.as_posix(),
        "split_manifest_path": split_manifest_path.as_posix(),
        "split_manifest_sha256": split_digest,
        "cohort_sql_path": cohort_sql_path.as_posix(),
        "decision_path": (output / "calibration-decision.json").as_posix(),
        "experiment_record_path": (output / "experiment-record.json").as_posix(),
        "db_url_env": "SYNTHETIC_ONLY",
        "holdout_accessed": False,
    }
    calibration_digest = _write_json(calibration_config, calibration_payload)
    holdout_config = tmp_path / "holdout-config.json"
    _write_json(
        holdout_config,
        {
            "schema_version": 1,
            "experiment_id": "synthetic-wp27",
            "phase": "holdout",
            "status": "pre_registered_not_run",
            "require_clean_provenance": False,
            "code_commit": "synthetic-current-code",
            "data_source_commit": "synthetic-source",
            "calibration_config_path": calibration_config.as_posix(),
            "calibration_config_sha256": calibration_digest,
            "required_calibration_decision": (output / "calibration-decision.json").as_posix(),
            "decision_sha256_must_be_supplied_to_holdout_command": True,
            "scoring_variants": ["raw", "calibrated"],
            "constant_baseline_included": False,
            "prevalence_role": "descriptive_context_only",
            "bootstrap": {"replicates": 2000, "seed": 0, "interval": "95_percentile"},
            "slice_support": {"shots": 50, "goals": 5, "misses": 5, "matches": 10},
            "distance_bands": ["[0,10)", "[10,20)", "[20,30)", "[30,+inf)"],
            "distance_unit": "StatsBomb coordinate units",
            "visible_angle_unit": "radians",
            "holdout_tournament": "Euro2024",
            "one_supervised_execution": True,
            "post_run_real_row_reload": False,
            "output_dir": output.as_posix(),
            "experiment_record_path": (output / "experiment-record.json").as_posix(),
            "published_evidence_report": (tmp_path / "published-evidence.md").as_posix(),
            "published_model_card": (tmp_path / "published-model-card.md").as_posix(),
            "db_url_env": "SYNTHETIC_ONLY",
        },
    )
    calibration_rows = tuple(
        replace(
            row,
            shot_id=f"calibration-{index}",
            match_id=2,
            fold=None,
            competition_id=43,
            season_id=106,
        )
        for index, row in enumerate(base_rows)
    )
    holdout_rows = tuple(
        replace(
            row,
            shot_id=f"holdout-{index}",
            match_id=3,
            fold=None,
            competition_id=55,
            season_id=282,
        )
        for index, row in enumerate(base_rows)
    )
    return SyntheticWP27(calibration_config, holdout_config, calibration_rows, holdout_rows)


def _synthetic_decision(
    path: Path, pins: BaseModelPins, base_identity: Mapping[str, object]
) -> CalibrationDecision:
    config_digest = "a" * 64
    execution: dict[str, object] = {
        "input_config_sha256": config_digest,
        "code_commit": "synthetic-current-code",
        "uv_lock_sha256": "b" * 64,
    }
    payload: dict[str, object] = {
        "schema_version": 1,
        "rule_version": CALIBRATION_RULE_VERSION,
        "calibration_split": "WC2022",
        "calibration_fit_scope": "WC2022_only",
        "holdout_accessed": False,
        "adopted_variant": "raw",
        "base_identity": dict(base_identity),
        "registered_base": pins.as_dict(),
        "calibration_config_sha256": config_digest,
        "execution_provenance": execution,
        "execution_provenance_sha256": exact_payload_sha256(execution),
        "platt_slope": 1.0,
        "platt_intercept": 0.0,
        "platt_parameter_sha256": platt_parameter_digest(1.0, 0.0),
        "raw_anchor_reliability": [],
        "adoption": {
            "rule_version": CALIBRATION_RULE_VERSION,
            "adopted_variant": "raw",
        },
    }
    write_calibration_decision(path, payload)
    return load_calibration_decision(path)


def test_raw_anchor_reliability_uses_the_same_rows_for_both_variants() -> None:
    raw = np.asarray([0.19, 0.21, 0.39, 0.41, 0.59, 0.61, 0.79, 0.81, 1.0])
    calibrated = np.asarray([0.99] * len(raw))
    y = np.asarray([0, 1, 0, 1, 0, 1, 0, 1, 1], dtype=np.int_)

    paired = paired_raw_anchor_reliability(y, raw, calibrated)
    assert [entry["count"] for entry in paired] == [1, 2, 2, 2, 2]
    assert [entry["positive_count"] for entry in paired] == [0, 1, 1, 1, 2]
    assert paired[0]["calibrated_mean_prediction"] == 0.99
    # A variant-specific table would put every calibrated row in the final bin. It is not the
    # table used here, because the raw-defined membership remains visible and unchanged.


def test_raw_anchor_bin_boundaries_are_left_closed_and_last_bin_includes_one() -> None:
    probabilities = np.asarray([0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
    paired = paired_raw_anchor_reliability(
        np.asarray([0, 0, 0, 0, 0, 1], dtype=np.int_),
        probabilities,
        probabilities,
    )
    assert [entry["count"] for entry in paired] == [1, 1, 1, 1, 2]


def test_adoption_rule_reads_raw_anchor_groups_not_variant_specific_bins() -> None:
    raw = np.repeat(np.asarray([0.1, 0.3, 0.5, 0.7, 0.9]), 100)
    calibrated = raw.copy()
    calibrated[:100] = 0.2  # Crosses the raw 0.2 boundary in a variant-specific table.
    y = np.concatenate(
        [
            np.r_[np.ones(20), np.zeros(80)],
            np.r_[np.ones(30), np.zeros(70)],
            np.r_[np.ones(50), np.zeros(50)],
            np.r_[np.ones(70), np.zeros(30)],
            np.r_[np.ones(90), np.zeros(10)],
        ]
    ).astype(int)

    decision = decide_calibration_adoption(
        y,
        raw,
        calibrated,
        platt_slope=1.0,
        platt_intercept=0.0,
    )
    assert decision["rule_version"] == CALIBRATION_RULE_VERSION
    assert decision["supported_bins"] == 5
    assert decision["adopted_variant"] == "calibrated"
    assert (
        float(cast(float, decision["calibrated_max_abs_deviation_supported"])) < ADOPTION_TOLERANCE
    )


def test_adoption_rejects_calibration_when_no_raw_anchor_bin_is_supported() -> None:
    raw = np.asarray([0.1] * 99)
    calibrated = np.asarray([0.2] * 99)
    y = np.asarray([0, 1] * 49 + [0])

    decision = decide_calibration_adoption(
        y,
        raw,
        calibrated,
        platt_slope=1.0,
        platt_intercept=0.0,
    )
    assert decision["supported_bins"] == 0
    assert decision["adopted_variant"] == "raw"
    assert "no_supported_raw_anchor_bins" in cast(Sequence[str], decision["rejection_reasons"])


def test_adoption_rejects_a_nonpositive_platt_slope_even_if_other_checks_pass() -> None:
    raw = np.repeat(np.asarray([0.1, 0.3, 0.5, 0.7, 0.9]), 100)
    calibrated = raw.copy()
    y = np.concatenate(
        [
            np.r_[np.ones(10), np.zeros(90)],
            np.r_[np.ones(30), np.zeros(70)],
            np.r_[np.ones(50), np.zeros(50)],
            np.r_[np.ones(70), np.zeros(30)],
            np.r_[np.ones(90), np.zeros(10)],
        ]
    ).astype(int)
    decision = decide_calibration_adoption(
        y,
        raw,
        calibrated,
        platt_slope=0.0,
        platt_intercept=0.0,
    )
    assert decision["adopted_variant"] == "raw"
    assert "platt_slope_not_finite_positive" in cast(Sequence[str], decision["rejection_reasons"])


@pytest.mark.parametrize(
    ("improvement", "expected_variant"),
    [(ADOPTION_TOLERANCE, "calibrated"), (ADOPTION_TOLERANCE / 2.0, "raw")],
)
def test_adoption_deviation_improvement_has_an_inclusive_exact_1e_12_boundary(
    improvement: float, expected_variant: str
) -> None:
    y = np.r_[np.ones(20), np.zeros(80)].astype(np.int_)
    raw = np.full(100, 0.3)
    calibrated = np.full(100, 0.3 - improvement)

    decision = decide_calibration_adoption(
        y,
        raw,
        calibrated,
        platt_slope=1.0,
        platt_intercept=0.0,
    )
    assert decision["adopted_variant"] == expected_variant


def test_calibration_decision_is_content_hashed_and_immutable(tmp_path: Path) -> None:
    identity = BaseModelIdentity.synthetic()
    payload = {
        "schema_version": 1,
        "rule_version": CALIBRATION_RULE_VERSION,
        "base_identity": identity.as_dict(),
        "adopted_variant": "raw",
    }
    path = tmp_path / "calibration-decision.json"
    written = write_calibration_decision(path, payload)
    assert written == load_calibration_decision(path)

    with pytest.raises(CalibrationDecisionError):
        path.write_text(
            json.dumps({"decision_sha256": "0" * 64, "decision": payload}),
            encoding="utf-8",
        )
        load_calibration_decision(path)


def test_calibration_decision_round_trips_platt_parameters_exactly(tmp_path: Path) -> None:
    slope = float.fromhex("0x1.3c0ca428c59fbp+0")
    intercept = float.fromhex("-0x1.9b1f5a7809f0cp-4")
    path = tmp_path / "calibration-decision.json"
    written = write_calibration_decision(
        path,
        {
            "schema_version": 1,
            "rule_version": CALIBRATION_RULE_VERSION,
            "base_identity": BaseModelIdentity.synthetic().as_dict(),
            "adopted_variant": "raw",
            "platt_slope": slope,
            "platt_intercept": intercept,
        },
    )

    loaded = load_calibration_decision(path)
    assert float(cast(float, loaded.payload["platt_slope"])).hex() == slope.hex()
    assert float(cast(float, loaded.payload["platt_intercept"])).hex() == intercept.hex()
    assert loaded.decision_sha256 == written.decision_sha256
    assert platt_parameter_digest(slope, intercept) != platt_parameter_digest(
        np.nextafter(slope, np.inf), intercept
    )


def test_frozen_base_requires_external_registered_pins(tmp_path: Path) -> None:
    pins, _rows = _synthetic_base(tmp_path)
    assert freeze_base_model(pins).identity.model_pickle_sha256 == pins.model_pickle_sha256

    with pytest.raises(CalibrationContractError, match="externally pinned"):
        freeze_base_model(replace(pins, model_pickle_sha256="f" * 64))


def test_real_phase_configs_are_byte_pinned_to_the_registered_base() -> None:
    assert _sha(wp2_7.DEFAULT_CALIBRATION_CONFIG_PATH) == wp2_7.DEFAULT_CALIBRATION_CONFIG_SHA256
    assert _sha(wp2_7.DEFAULT_HOLDOUT_CONFIG_PATH) == wp2_7.DEFAULT_HOLDOUT_CONFIG_SHA256
    calibration = json.loads(wp2_7.DEFAULT_CALIBRATION_CONFIG_PATH.read_text(encoding="utf-8"))
    assert calibration["frozen_base"] == wp2_7.EXPECTED_BASE_PIN_PAYLOAD
    holdout = json.loads(wp2_7.DEFAULT_HOLDOUT_CONFIG_PATH.read_text(encoding="utf-8"))
    assert holdout["calibration_config_sha256"] == wp2_7.DEFAULT_CALIBRATION_CONFIG_SHA256


def test_holdout_phase_rejects_a_mismatched_decision_before_loader(tmp_path: Path) -> None:
    fixture = _synthetic_wp27(tmp_path)
    run_calibration_phase(
        config_path=fixture.calibration_config,
        calibration_loader=lambda: fixture.calibration_rows,
        expected_shots=len(fixture.calibration_rows),
        expected_matches=1,
    )
    loader_calls = 0

    def forbidden_loader() -> list[ShotRow]:
        nonlocal loader_calls
        loader_calls += 1
        raise AssertionError("mismatched decisions must fail before holdout access")

    with pytest.raises(RuntimeError, match="does not match"):
        run_holdout_phase(
            config_path=fixture.holdout_config,
            holdout_loader=forbidden_loader,
            expected_decision_sha256="f" * 64,
            expected_shots=None,
            expected_matches=None,
        )
    assert loader_calls == 0


def test_calibration_phase_uses_only_its_injected_calibration_loader(tmp_path: Path) -> None:
    fixture = _synthetic_wp27(tmp_path)
    loader_calls = 0

    def calibration_loader() -> Sequence[ShotRow]:
        nonlocal loader_calls
        loader_calls += 1
        return fixture.calibration_rows

    decision = run_calibration_phase(
        config_path=fixture.calibration_config,
        calibration_loader=calibration_loader,
        expected_shots=len(fixture.calibration_rows),
        expected_matches=1,
    )
    assert loader_calls == 1
    assert decision.payload["holdout_accessed"] is False
    provenance = cast(Mapping[str, object], decision.payload["execution_provenance"])
    assert provenance["input_config_sha256"] == _sha(fixture.calibration_config)


def test_calibration_db_path_requests_only_the_calibration_partition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pins, base_rows = _synthetic_base(tmp_path)
    frozen = freeze_base_model(pins)
    assignments = parse_match_assignments(
        (ROOT / "data/model/wp2_3_match_assignments.csv").read_text(encoding="utf-8")
    )
    calibration_ids = sorted(assignments.ids_for("calibration"))
    rows = [
        replace(
            base_rows[index % len(base_rows)],
            shot_id=f"db-calibration-{index}",
            match_id=match_id,
            fold=None,
            y=index % 2,
            competition_id=43,
            season_id=106,
        )
        for index, match_id in enumerate(calibration_ids)
    ]
    requested_splits: list[str] = []

    class SyntheticConnection:
        def __enter__(self) -> SyntheticConnection:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    original_load_config = wp2_7._load_phase_config

    def load_config_without_clean_tree(
        path: str | Path,
        phase: Literal["calibration", "holdout"],
        *,
        enforce_registered: bool,
    ) -> wp2_7.PhaseConfig:
        return original_load_config(path, phase, enforce_registered=False)

    def fake_load_partition(
        _connection: object, _sql: str, _assignments: object, split: str
    ) -> list[ShotRow]:
        requested_splits.append(split)
        return rows

    monkeypatch.setattr(wp2_7, "_load_phase_config", load_config_without_clean_tree)
    monkeypatch.setattr(wp2_7, "_resolve_execution_provenance", lambda _config: {})
    monkeypatch.setattr(wp2_7, "freeze_base_model", lambda _pins: frozen)
    monkeypatch.setattr(wp2_7, "open_db", lambda _url: SyntheticConnection())
    monkeypatch.setattr(wp2_7, "load_partition_cohort", fake_load_partition)
    monkeypatch.setattr(
        wp2_7,
        "write_calibration_decision",
        lambda _path, payload: CalibrationDecision("a" * 64, payload),
    )
    decision = run_calibration_phase(
        db_url="synthetic://no-database-access",
        expected_shots=None,
        expected_matches=None,
    )
    assert requested_splits == ["calibration"]
    assert decision.payload["holdout_accessed"] is False


def test_holdout_session_materializes_rows_once() -> None:
    calls = 0

    def loader() -> list[object]:
        nonlocal calls
        calls += 1
        return [object()]

    session = HoldoutAccessSession(loader)
    assert len(session.open()) == 1
    with pytest.raises(HoldoutAccessError):
        session.open()
    assert calls == 1


def test_audit_cannot_finalize_before_holdout_closed(tmp_path: Path) -> None:
    audit = HoldoutAccessAudit(
        run_id="synthetic",
        decision_sha256="a" * 64,
        holdout_open_count=1,
        membership_sha256="b" * 64,
        n_rows=2,
        n_matches=1,
        n_goals=1,
        n_misses=1,
        execution_provenance_sha256="c" * 64,
        stages=(
            "holdout_open",
            "membership_asserted",
            "scored",
            "bootstrap",
            "slices",
            "evidence_written",
        ),
    )
    with pytest.raises(HoldoutAccessError, match="before holdout_closed"):
        finalize_holdout_audit(
            tmp_path,
            {"candidate": "full_minus_presence", "adopted_variant": "raw"},
            audit,
            experiment_record_path=tmp_path / "experiment-record.json",
            execution_provenance={},
            experiment_id="synthetic",
        )


def test_synthetic_holdout_runner_never_refits_and_finalizes_metadata_after_close(
    tmp_path: Path,
) -> None:
    fixture = _synthetic_wp27(tmp_path)
    decision = run_calibration_phase(
        config_path=fixture.calibration_config,
        calibration_loader=lambda: fixture.calibration_rows,
        expected_shots=len(fixture.calibration_rows),
        expected_matches=1,
    )
    loader_calls = 0

    def holdout_loader() -> Sequence[ShotRow]:
        nonlocal loader_calls
        loader_calls += 1
        return fixture.holdout_rows

    audit = run_holdout_phase(
        config_path=fixture.holdout_config,
        holdout_loader=holdout_loader,
        expected_decision_sha256=decision.decision_sha256,
        expected_shots=len(fixture.holdout_rows),
        expected_matches=1,
        run_id="synthetic-holdout",
    )
    assert loader_calls == 1
    assert audit.holdout_open_count == 1
    assert audit.n_goals == 10
    assert audit.n_misses == 10
    assert len(audit.evidence_files_sha256) == 8
    assert audit.stages[-3:] == ("holdout_closed", "experiment_record_written", "audit_finalized")
    payload = verify_holdout_audit_metadata(tmp_path / "experiment" / "holdout-access-audit.json")
    assert payload["holdout_open_count"] == 1
    metrics = json.loads((tmp_path / "experiment" / "holdout-metrics.json").read_text())
    assert set(metrics["variants"]) == {"raw", "calibrated"}
    assert metrics["bootstrap"]["repetitions"] == 2_000
    assert metrics["bootstrap"]["seed"] == 0
    record = json.loads((tmp_path / "experiment" / "experiment-record.json").read_text())
    assert record["status"] == "holdout_complete_pending_independent_review"
    with pytest.raises(RuntimeError, match="existing row-derived evidence"):
        run_holdout_phase(
            config_path=fixture.holdout_config,
            holdout_loader=holdout_loader,
            expected_decision_sha256=decision.decision_sha256,
            expected_shots=len(fixture.holdout_rows),
            expected_matches=1,
        )
    assert loader_calls == 1


def test_holdout_rejects_noncontract_bootstrap_before_loader(tmp_path: Path) -> None:
    fixture = _synthetic_wp27(tmp_path)
    payload = json.loads(fixture.holdout_config.read_text(encoding="utf-8"))
    payload["bootstrap"] = {"replicates": 1, "seed": 99, "interval": "95_percentile"}
    _write_json(fixture.holdout_config, payload)
    loader_calls = 0

    def forbidden_loader() -> Sequence[ShotRow]:
        nonlocal loader_calls
        loader_calls += 1
        return fixture.holdout_rows

    with pytest.raises(RuntimeError, match="exactly 2,000 replicates with seed 0"):
        run_holdout_phase(
            config_path=fixture.holdout_config,
            holdout_loader=forbidden_loader,
            expected_decision_sha256="0" * 64,
        )
    assert loader_calls == 0


def test_holdout_refuses_missing_decision_before_loader(tmp_path: Path) -> None:
    fixture = _synthetic_wp27(tmp_path)
    loader_calls = 0

    def forbidden_loader() -> Sequence[ShotRow]:
        nonlocal loader_calls
        loader_calls += 1
        return fixture.holdout_rows

    with pytest.raises(CalibrationDecisionError, match="cannot read calibration decision"):
        run_holdout_phase(
            config_path=fixture.holdout_config,
            holdout_loader=forbidden_loader,
            expected_decision_sha256="0" * 64,
        )
    assert loader_calls == 0


def test_holdout_refuses_execution_identity_drift_before_loader(tmp_path: Path) -> None:
    fixture = _synthetic_wp27(tmp_path)
    decision = run_calibration_phase(
        config_path=fixture.calibration_config,
        calibration_loader=lambda: fixture.calibration_rows,
        expected_shots=len(fixture.calibration_rows),
        expected_matches=1,
    )
    holdout_payload = json.loads(fixture.holdout_config.read_text(encoding="utf-8"))
    holdout_payload["data_source_commit"] = "different-synthetic-source"
    _write_json(fixture.holdout_config, holdout_payload)
    loader_calls = 0

    def forbidden_loader() -> Sequence[ShotRow]:
        nonlocal loader_calls
        loader_calls += 1
        return fixture.holdout_rows

    with pytest.raises(RuntimeError, match="identity differs"):
        run_holdout_phase(
            config_path=fixture.holdout_config,
            holdout_loader=forbidden_loader,
            expected_decision_sha256=decision.decision_sha256,
        )
    assert loader_calls == 0


def test_holdout_refuses_source_bundle_drift_before_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _synthetic_wp27(tmp_path)
    decision = run_calibration_phase(
        config_path=fixture.calibration_config,
        calibration_loader=lambda: fixture.calibration_rows,
        expected_shots=len(fixture.calibration_rows),
        expected_matches=1,
    )
    recorded = cast(Mapping[str, object], decision.payload["execution_provenance"])
    drifted = dict(recorded)
    source_files = dict(cast(Mapping[str, str], recorded["source_files_sha256"]))
    source_files["backend/src/touchline/modeling/experiment.py"] = "f" * 64
    drifted["source_files_sha256"] = source_files
    drifted["source_bundle_sha256"] = "e" * 64
    monkeypatch.setattr(wp2_7, "_resolve_execution_provenance", lambda _config: drifted)
    loader_calls = 0

    def forbidden_loader() -> Sequence[ShotRow]:
        nonlocal loader_calls
        loader_calls += 1
        return fixture.holdout_rows

    with pytest.raises(RuntimeError, match="identity differs"):
        run_holdout_phase(
            config_path=fixture.holdout_config,
            holdout_loader=forbidden_loader,
            expected_decision_sha256=decision.decision_sha256,
        )
    assert loader_calls == 0


def test_cli_exposes_no_bootstrap_override() -> None:
    with pytest.raises(SystemExit):
        wp2_7.main(["holdout", "--decision-sha256", "0" * 64, "--bootstrap-repetitions", "1"])


def test_d11_support_constant_is_the_locked_value() -> None:
    assert D11_MIN_SUPPORT == 100


def test_holdout_result_contains_only_the_frozen_logistic_pair(tmp_path: Path) -> None:
    pins, base_rows = _synthetic_base(tmp_path)
    frozen = freeze_base_model(pins)
    rows = [
        replace(row, shot_id=f"synthetic-{index}", match_id=900 + index // 2)
        for index, row in enumerate(base_rows)
    ]
    decision_path = tmp_path / "calibration-decision.json"
    decision = _synthetic_decision(decision_path, pins, frozen.identity.as_dict())
    result = evaluate_holdout_rows(rows, frozen, decision)
    variants = cast(Mapping[str, object], result["variants"])
    assert set(variants) == {"raw", "calibrated"}
    assert "constant" not in variants
    assert result["adopted_variant"] == "raw"


def test_holdout_refuses_a_calibration_decision_for_a_different_base(tmp_path: Path) -> None:
    pins, rows = _synthetic_base(tmp_path)
    frozen = freeze_base_model(pins)
    mismatched_identity = frozen.identity.as_dict()
    mismatched_identity["estimator_state_sha256"] = "f" * 64
    decision_path = tmp_path / "mismatched-calibration-decision.json"
    decision = _synthetic_decision(decision_path, pins, mismatched_identity)
    with pytest.raises(CalibrationContractError):
        evaluate_holdout_rows(rows, frozen, decision)


@pytest.mark.parametrize("component", ["estimator", "preprocessing"])
def test_frozen_base_detects_in_memory_identity_mutation(component: str, tmp_path: Path) -> None:
    pins, _rows = _synthetic_base(tmp_path)
    frozen = freeze_base_model(pins)
    if component == "estimator":
        frozen.bundle.estimator.coef_[0, 0] += 0.01
    else:
        cast(dict[str, float], frozen.bundle.scaler.mean)["distance_to_goal"] += 0.01
    with pytest.raises(CalibrationContractError):
        assert_frozen_base_unchanged(frozen)
