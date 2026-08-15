"""Build and inspect the real WP3.1 production image and its fail-fast bundle behavior."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_BUNDLE = ROOT / "backend/model-release/exp-20260810-wp2_8-release"
CONTAINER_BUNDLE = "/app/backend/model-release/exp-20260810-wp2_8-release"
DEFAULT_IMAGE = "touchline-api:wp3-1-acceptance"


def _run(command: list[str], *, expect_success: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    if expect_success and result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _mount(path: Path) -> str:
    return f"{path.resolve()}:{CONTAINER_BUNDLE}:ro"


def _canonical(payload: dict[str, Any]) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, indent=2, separators=(",", ": "), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def _assert_container_failure(image: str, bundle: Path, expected_code: str, label: str) -> None:
    result = _run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "python",
            "-v",
            _mount(bundle),
            image,
            "-c",
            "from touchline.serving import ModelRuntime; ModelRuntime.load()",
        ],
        expect_success=False,
    )
    if result.returncode == 0 or expected_code not in result.stderr:
        raise RuntimeError(
            f"{label} packaged bundle did not fail closed with {expected_code}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()
    if not args.skip_build:
        _run(["docker", "build", "-t", args.image, "."])

    probe = """
import json
import math
from pathlib import Path
from touchline.serving import (
    EXPECTED_FILES,
    ModelRuntime,
    PredictionInput,
    SERVING_BUNDLE_DIR,
)
actual = {path.name for path in SERVING_BUNDLE_DIR.iterdir() if path.is_file()}
assert actual == set(EXPECTED_FILES), (actual, EXPECTED_FILES)
assert not Path('/app/artifacts').exists()
assert not Path('/app/experiments').exists()
runtime = ModelRuntime.load()
assert runtime.provenance()['artifact_sha256'] == (
    '9aeac9468c00bd1b93c771e454e48ca29e2eb759cf71836182a782d674bfadca'
)
assert runtime.provenance()['serving_manifest_sha256'] == (
    '68cee3ab4f06c280421f848de36d59b3db39d8c3ea7ece7765a4ba29e3a7ae5c'
)
oracle = json.loads(
    Path('/app/backend/tests/fixtures/wp3_1_golden_cases.json').read_text(encoding='utf-8')
)
case = next(item for item in oracle['cases'] if item['name'] == 'reference_levels')
request = case['request']
actual_probability = runtime.predict(
    PredictionInput(
        location_x=request['location_x'],
        location_y=request['location_y'],
        body_part=request['body_part'],
        technique=request['technique'],
        play_pattern=request['play_pattern'],
    )
)
assert math.isclose(
    actual_probability,
    case['expected']['calibrated_probability'],
    rel_tol=0.0,
    abs_tol=oracle['absolute_tolerance'],
), (actual_probability, case['expected']['calibrated_probability'])
"""
    _run(["docker", "run", "--rm", "--entrypoint", "python", args.image, "-c", probe])

    for failure, filename, expected_code in (
        ("missing", "model.pkl", "serving_bundle_missing"),
        ("corrupt", "model.pkl", "serving_bundle_hash_mismatch"),
    ):
        with tempfile.TemporaryDirectory(prefix=f"wp31-{failure}-") as temporary:
            bundle = Path(temporary) / "bundle"
            shutil.copytree(SOURCE_BUNDLE, bundle)
            target = bundle / filename
            if failure == "missing":
                target.unlink()
            else:
                target.write_bytes(b"deliberately corrupt packaged model")
            _assert_container_failure(args.image, bundle, expected_code, failure)

    with tempfile.TemporaryDirectory(prefix="wp31-schema-") as temporary:
        bundle = Path(temporary) / "bundle"
        shutil.copytree(SOURCE_BUNDLE, bundle)
        manifest_path = bundle / "serving-manifest.json"
        envelope = json.loads(manifest_path.read_text(encoding="utf-8"))
        envelope["serving_bundle"]["schema_version"] = 999
        envelope["serving_manifest_sha256"] = hashlib.sha256(
            _canonical(envelope["serving_bundle"])
        ).hexdigest()
        manifest_path.write_bytes(_canonical(envelope))
        _assert_container_failure(
            args.image, bundle, "release_schema_unsupported", "unsupported-schema"
        )

    print("WP3.1 Docker acceptance PASS")


if __name__ == "__main__":
    main()
