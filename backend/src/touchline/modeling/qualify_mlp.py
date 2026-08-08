"""Finalize two fresh CPU reproductions and two RTX CUDA qualifications into one record."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import numpy as np

from touchline.modeling.experiment import record_path
from touchline.modeling.metrics import canonical_metrics_json


class QualificationError(RuntimeError):
    """Fresh runs, artifact identities or CPU/CUDA parity failed qualification."""


def _load(path: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def _canonical_digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_metrics_json(payload)).hexdigest()


def finalize_qualification(
    *,
    cpu_paths: Sequence[Path],
    cuda_paths: Sequence[Path],
    canonical_metrics_path: Path,
    canonical_history_path: Path,
    output_path: Path,
) -> dict[str, object]:
    """Require exact within-device repeats and publish same-weight cross-device parity."""
    if len(cpu_paths) != 2 or len(cuda_paths) != 2:
        raise QualificationError("qualification requires exactly two CPU and two CUDA payloads")
    expected_output = canonical_metrics_path.parent / "cuda-qualification.json"
    if output_path.resolve() != expected_output.resolve():
        raise QualificationError(f"qualification staging output must be {expected_output}")
    cpu = [_load(path) for path in cpu_paths]
    cuda = [_load(path) for path in cuda_paths]
    if canonical_metrics_json(cpu[0]) != canonical_metrics_json(cpu[1]):
        raise QualificationError("fresh canonical CPU reproduction payloads differ")
    if canonical_metrics_json(cuda[0]) != canonical_metrics_json(cuda[1]):
        raise QualificationError("fresh CUDA qualification payloads differ")

    canonical = _load(canonical_metrics_path)
    canonical_history = _load(canonical_history_path)
    frozen_selection = str(canonical["selection_incumbent"])
    for name, payloads in (("CPU", cpu), ("CUDA", cuda)):
        for payload in payloads:
            if str(payload["frozen_canonical_cpu_selection"]) != frozen_selection:
                raise QualificationError(f"{name} payload did not consume the frozen CPU selection")
    if any(payload.get("selection_effect") != "none" for payload in cuda):
        raise QualificationError("CUDA payload is not selection-isolated")
    if cpu[0]["final_parameter_digest"] != canonical["parameter_digest"]:
        raise QualificationError("CPU reproduction final parameters differ from canonical artifact")
    candidates = cast(Mapping[str, object], canonical["candidates"])
    canonical_mlp = candidates["pytorch_mlp"]
    canonical_comparisons = (
        ("mlp_oof_metrics", canonical_mlp, "MLP metrics"),
        ("ordered_oof_predictions", canonical["ordered_oof_predictions"], "OOF predictions"),
        ("fold_parameter_digests", canonical["fold_parameter_digests"], "fold parameter digests"),
        ("training_history", canonical_history, "training history"),
    )
    for field, expected, label in canonical_comparisons:
        actual_digest = _canonical_digest({"value": cpu[0][field]})
        expected_digest = _canonical_digest({"value": expected})
        if actual_digest != expected_digest:
            raise QualificationError(f"CPU reproduction {label} differ from canonical evidence")

    cpu_reload = cast(Mapping[str, object], cpu[0]["artifact_reload"])
    cuda_reload = cast(Mapping[str, object], cuda[0]["artifact_reload"])
    for key in ("weights_sha256", "parameter_digest", "preprocessing_digest", "ordered_shot_ids"):
        if cpu_reload[key] != cuda_reload[key] or cpu_reload[key] != canonical.get(key):
            if key == "ordered_shot_ids" and cpu_reload[key] == cuda_reload[key]:
                continue
            raise QualificationError(f"CPU/CUDA canonical artifact reload disagrees on {key}")
    cpu_probabilities = np.asarray(cpu_reload["probabilities"], dtype=np.float64)
    cuda_probabilities = np.asarray(cuda_reload["probabilities"], dtype=np.float64)
    if cpu_probabilities.shape != cuda_probabilities.shape:
        raise QualificationError("CPU/CUDA artifact prediction shapes differ")
    difference = np.abs(cpu_probabilities - cuda_probabilities)
    if not np.allclose(cpu_probabilities, cuda_probabilities, atol=1e-6, rtol=1e-5):
        raise QualificationError(
            f"same-weight CPU/CUDA inference parity failed; max difference {difference.max()}"
        )
    record = {
        "qualification_schema_version": 1,
        "qualification_only": True,
        "selection_effect": "none",
        "frozen_canonical_cpu_selection": frozen_selection,
        "cpu_reproduction_payload_sha256": _canonical_digest(cpu[0]),
        "cuda_qualification_payload_sha256": _canonical_digest(cuda[0]),
        "source_payload_paths": {
            "cpu": [record_path(path) for path in cpu_paths],
            "cuda": [record_path(path) for path in cuda_paths],
        },
        "artifact_identity": {
            key: canonical[key]
            for key in ("weights_sha256", "parameter_digest", "preprocessing_digest")
        },
        "same_weight_inference_parity": {
            "atol": 1e-6,
            "rtol": 1e-5,
            "mean_probability_difference": float(difference.mean()),
            "max_probability_difference": float(difference.max()),
        },
        "canonical_cpu_reproduction": cpu[0],
        "cuda_qualification": cuda[0],
    }
    output_path.write_bytes(canonical_metrics_json(record))
    return record


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="touchline.modeling.qualify_mlp")
    parser.add_argument("--cpu-run", action="append", required=True)
    parser.add_argument("--cuda-run", action="append", required=True)
    parser.add_argument("--canonical-metrics", required=True)
    parser.add_argument("--canonical-history", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        finalize_qualification(
            cpu_paths=[Path(value) for value in args.cpu_run],
            cuda_paths=[Path(value) for value in args.cuda_run],
            canonical_metrics_path=Path(args.canonical_metrics),
            canonical_history_path=Path(args.canonical_history),
            output_path=Path(args.output),
        )
        from touchline.modeling.train_mlp import publish_qualified_experiment

        publish_qualified_experiment(
            canonical_metrics_path=Path(args.canonical_metrics),
            canonical_history_path=Path(args.canonical_history),
            qualification_path=Path(args.output),
        )
        return 0
    except (OSError, ValueError, QualificationError) as exc:
        print(f"WP2.6 qualification failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
