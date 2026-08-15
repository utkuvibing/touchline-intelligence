"""Build and inspect the real WP3.1 production image and its fail-fast bundle behavior."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()
    if not args.skip_build:
        _run(["docker", "build", "-t", args.image, "."])

    probe = """
from pathlib import Path
from touchline.serving import EXPECTED_FILES, ModelRuntime, SERVING_BUNDLE_DIR
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
            result = _run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--entrypoint",
                    "python",
                    "-v",
                    _mount(bundle),
                    args.image,
                    "-c",
                    "from touchline.serving import ModelRuntime; ModelRuntime.load()",
                ],
                expect_success=False,
            )
            if result.returncode == 0 or expected_code not in result.stderr:
                raise RuntimeError(
                    f"{failure} packaged bundle did not fail closed with {expected_code}\n"
                    f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
                )

    print("WP3.1 Docker acceptance PASS")


if __name__ == "__main__":
    main()
