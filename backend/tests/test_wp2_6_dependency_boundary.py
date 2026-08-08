"""WP2.6 keeps training-only PyTorch available to developers and absent from production."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_modeling_group_and_platform_specific_torch_sources_are_locked() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["dependency-groups"]["modeling"] == ["torch==2.13.0"]
    assert project["tool"]["uv"]["default-groups"] == ["dev", "modeling"]
    sources = project["tool"]["uv"]["sources"]["torch"]
    assert sources == [
        {"index": "pytorch-cu130", "marker": "sys_platform == 'win32'"},
        {"index": "pytorch-cpu", "marker": "sys_platform != 'win32'"},
    ]
    indexes = {entry["name"]: entry for entry in project["tool"]["uv"]["index"]}
    assert indexes["pytorch-cu130"] == {
        "name": "pytorch-cu130",
        "url": "https://download.pytorch.org/whl/cu130",
        "explicit": True,
    }
    assert indexes["pytorch-cpu"] == {
        "name": "pytorch-cpu",
        "url": "https://download.pytorch.org/whl/cpu",
        "explicit": True,
    }


def test_docker_excludes_every_default_dependency_group() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.count("--no-default-groups") == 2
    assert "--no-dev" not in dockerfile


def test_api_and_shared_modeling_package_do_not_import_torch() -> None:
    probe = (
        "import sys; import touchline.main; import touchline.modeling; "
        "raise SystemExit(1 if 'torch' in sys.modules else 0)"
    )
    result = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, check=False)
    assert result.returncode == 0


def test_ci_builds_the_production_image_and_proves_torch_is_absent() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "docker build -t touchline-api:ci ." in workflow
    assert 'importlib.util.find_spec("torch") is None' in workflow
    assert "import touchline.main" in workflow
