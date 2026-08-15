"""WP3.1 serving-bundle startup contracts.

The seam is ``ModelRuntime.load``: callers either receive one fully validated runtime or a typed
startup failure. Tests copy the committed minimal bundle so corruption never touches qualified or
packaged evidence.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from touchline.serving import ModelRuntime, ServingBundleError

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "backend" / "model-release" / "exp-20260810-wp2_8-release"
EXPECTED_FILES = {
    "artifact-manifest.json",
    "calibration-decision.json",
    "holdout-metrics.json",
    "model.pkl",
    "serving-manifest.json",
    "wp2_8-release-manifest.json",
}


def _copy_bundle(tmp_path: Path) -> Path:
    destination = tmp_path / "bundle"
    shutil.copytree(BUNDLE, destination)
    return destination


def _canonical(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, separators=(",", ": "), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def _rewrite_serving_manifest(path: Path, mutate: Any) -> None:
    manifest_path = path / "serving-manifest.json"
    envelope = json.loads(manifest_path.read_text(encoding="utf-8"))
    mutate(envelope["serving_bundle"])
    envelope["serving_manifest_sha256"] = hashlib.sha256(
        _canonical(envelope["serving_bundle"])
    ).hexdigest()
    manifest_path.write_bytes(_canonical(envelope))


def test_committed_bundle_is_minimal_and_loads_as_the_qualified_release() -> None:
    assert {path.name for path in BUNDLE.iterdir()} == EXPECTED_FILES

    runtime = ModelRuntime.load(BUNDLE)
    metadata = runtime.metadata()

    assert metadata["release_id"] == "exp-20260810-wp2_8-release"
    assert metadata["serving_manifest_sha256"] == (
        "68cee3ab4f06c280421f848de36d59b3db39d8c3ea7ece7765a4ba29e3a7ae5c"
    )
    assert metadata["artifact_sha256"] == (
        "9aeac9468c00bd1b93c771e454e48ca29e2eb759cf71836182a782d674bfadca"
    )
    assert metadata["calibration_decision_sha256"] == (
        "f5c9ccf665924069f755fbd669d4a9abada1e5791e957d3d436d42d500277e89"
    )


def test_missing_bundle_member_aborts_loading(tmp_path: Path) -> None:
    bundle = _copy_bundle(tmp_path)
    (bundle / "model.pkl").unlink()

    with pytest.raises(ServingBundleError, match="serving_bundle_missing"):
        ModelRuntime.load(bundle)


def test_corrupt_model_aborts_before_pickle_loading(tmp_path: Path) -> None:
    bundle = _copy_bundle(tmp_path)
    (bundle / "model.pkl").write_bytes(b"not a trusted pickle")

    with pytest.raises(ServingBundleError, match="serving_bundle_hash_mismatch"):
        ModelRuntime.load(bundle)


def test_serving_manifest_content_change_without_matching_digest_aborts(tmp_path: Path) -> None:
    bundle = _copy_bundle(tmp_path)
    manifest = bundle / "serving-manifest.json"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            '"bundle_id": "exp-20260810-wp2_8-release"', '"bundle_id": "tampered"'
        ),
        encoding="utf-8",
    )

    with pytest.raises(ServingBundleError, match="serving_bundle_hash_mismatch"):
        ModelRuntime.load(bundle)


def test_unsupported_serving_schema_aborts_even_with_valid_manifest_hash(tmp_path: Path) -> None:
    bundle = _copy_bundle(tmp_path)
    _rewrite_serving_manifest(bundle, lambda payload: payload.__setitem__("schema_version", 999))

    with pytest.raises(ServingBundleError, match="release_schema_unsupported"):
        ModelRuntime.load(bundle)


def test_unexpected_file_aborts_the_minimal_allow_list(tmp_path: Path) -> None:
    bundle = _copy_bundle(tmp_path)
    (bundle / "unrelated-experiment.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ServingBundleError, match="serving_bundle_unexpected_file"):
        ModelRuntime.load(bundle)


def test_unexpected_directory_also_aborts_the_minimal_allow_list(tmp_path: Path) -> None:
    bundle = _copy_bundle(tmp_path)
    (bundle / "unrelated-experiment").mkdir()

    with pytest.raises(ServingBundleError, match="serving_bundle_unexpected_file"):
        ModelRuntime.load(bundle)


def test_release_cross_check_rejects_a_self_consistent_wrong_model_hash(tmp_path: Path) -> None:
    bundle = _copy_bundle(tmp_path)
    model_path = bundle / "model.pkl"
    model_path.write_bytes(model_path.read_bytes() + b"tamper")
    wrong_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()

    def update_member(payload: dict[str, Any]) -> None:
        payload["files"]["model"]["sha256"] = wrong_hash

    _rewrite_serving_manifest(bundle, update_member)

    with pytest.raises(ServingBundleError, match="release_manifest_invalid"):
        ModelRuntime.load(bundle)
