"""Write the independent WP2 oracle fixture for WP3.1 serving parity.

This script deliberately imports no WP3.1 serving code. It evaluates raw cases through the
qualified WP2 geometry, preprocessing, artifact and calibration paths, after verifying canonical
WP2.8 identities. The frozen output is then an independent oracle for ModelRuntime tests.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from touchline.features.geometry import distance_to_goal, visible_goal_angle
from touchline.modeling.artifact import load_bundle
from touchline.modeling.calibration import PlattCalibrator, load_calibration_decision
from touchline.modeling.preprocessing import ShotRow, encode_rows

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "artifacts/models/exp-20260805-wp2_4-baselines/model.pkl"
DECISION = (
    ROOT
    / "experiments/shot_quality/exp-20260809-wp2_7-calibration-holdout/calibration-decision.json"
)
OUTPUT = ROOT / "backend/tests/fixtures/wp3_1_golden_cases.json"
MODEL_SHA256 = "9aeac9468c00bd1b93c771e454e48ca29e2eb759cf71836182a782d674bfadca"
DECISION_SHA256 = "f5c9ccf665924069f755fbd669d4a9abada1e5791e957d3d436d42d500277e89"

CASES: tuple[dict[str, object], ...] = (
    {
        "name": "reference_levels",
        "request": {
            "location_x": 112.0,
            "location_y": 40.0,
            "body_part": "Right Foot",
            "technique": "Normal",
            "play_pattern": "Regular Play",
        },
    },
    {
        "name": "retained_levels",
        "request": {
            "location_x": 108.0,
            "location_y": 36.0,
            "body_part": "Head",
            "technique": "Volley",
            "play_pattern": "From Corner",
        },
    },
    {
        "name": "rare_members",
        "request": {
            "location_x": 100.0,
            "location_y": 50.0,
            "body_part": "Other",
            "technique": "Backheel",
            "play_pattern": "Other",
        },
    },
    {
        "name": "unseen_levels",
        "request": {
            "location_x": 100.0,
            "location_y": 50.0,
            "body_part": "Future Body",
            "technique": "Future Technique",
            "play_pattern": "Future Pattern",
        },
    },
    {
        "name": "literal_rare_is_external_unseen",
        "request": {
            "location_x": 100.0,
            "location_y": 50.0,
            "body_part": "rare",
            "technique": "rare",
            "play_pattern": "rare",
        },
        # The approved external contract treats the encoder's internal column label as an unseen
        # source value. This oracle-only substitution passes that semantic case through WP2's
        # existing unseen-reference path; no WP3 runtime code participates.
        "wp2_oracle_categories": {
            "body_part": "__oracle_unseen_body__",
            "technique": "__oracle_unseen_technique__",
            "play_pattern": "__oracle_unseen_pattern__",
        },
    },
    {
        "name": "goal_line_between_posts",
        "request": {
            "location_x": 120.0,
            "location_y": 40.0,
            "body_part": "Right Foot",
            "technique": "Normal",
            "play_pattern": "Regular Play",
        },
    },
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(payload: object) -> str:
    return (
        json.dumps(payload, sort_keys=True, indent=2, separators=(",", ": "), ensure_ascii=True)
        + "\n"
    )


def main() -> None:
    if _sha256(MODEL) != MODEL_SHA256:
        raise RuntimeError("canonical WP2 model hash changed; refusing to generate a golden oracle")
    decision = load_calibration_decision(DECISION)
    if decision.decision_sha256 != DECISION_SHA256:
        raise RuntimeError("canonical WP2 calibration decision changed")
    bundle = load_bundle(MODEL)
    calibrator = PlattCalibrator(
        slope=float(decision.payload["platt_slope"]),
        intercept=float(decision.payload["platt_intercept"]),
    )
    generated: list[dict[str, Any]] = []
    for case in CASES:
        request = dict(case["request"])  # type: ignore[arg-type]
        oracle_categories = dict(case.get("wp2_oracle_categories", request))  # type: ignore[arg-type]
        x = float(request["location_x"])
        y = float(request["location_y"])
        row = ShotRow(
            shot_id=f"golden-{case['name']}",
            match_id=0,
            fold=None,
            competition_id=0,
            season_id=0,
            y=0,
            distance_to_goal=distance_to_goal(x, y),
            visible_goal_angle=visible_goal_angle(x, y),
            body_part_name=str(oracle_categories["body_part"]),
            technique_name=str(oracle_categories["technique"]),
            play_pattern_name=str(oracle_categories["play_pattern"]),
            first_time=None,
            under_pressure=None,
        )
        full, columns = encode_rows([row], bundle.vocabulary, bundle.scaler)
        selected = full[:, list(bundle.selected_indices)][0].tolist()
        logit = float(bundle.predict_logit([row])[0])
        generated.append(
            {
                "name": case["name"],
                "request": request,
                "expected": {
                    "distance_to_goal": row.distance_to_goal,
                    "visible_goal_angle": row.visible_goal_angle,
                    "all_columns": columns,
                    "selected_columns": list(bundle.selected_columns),
                    "selected_vector": selected,
                    "base_logit": logit,
                    "base_probability": float(bundle.predict_proba([row])[0]),
                    "calibrated_probability": float(calibrator.predict([logit])[0]),
                },
            }
        )
    payload = {
        "schema_version": 1,
        "oracle": "qualified_wp2_preprocessing_and_inference_path",
        "generated_by": "scripts/write_wp3_1_golden_cases.py",
        "model_sha256": MODEL_SHA256,
        "calibration_decision_sha256": DECISION_SHA256,
        "absolute_tolerance": 1e-12,
        "cases": generated,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(_canonical(payload), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
