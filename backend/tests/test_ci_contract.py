"""Release-critical GitHub Actions bootstrap contracts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_backend_ci_installs_a_pinned_verified_uv_release_without_a_manifest() -> None:
    """Keep CI independent of setup-uv's separately hosted version manifest."""
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    install_uv_step = workflow.split("- name: Install uv", maxsplit=1)[1].split(
        "\n      - ", maxsplit=1
    )[0]

    assert "setup-uv@" not in install_uv_step
    assert "UV_VERSION: 0.11.25" in install_uv_step
    assert (
        "UV_ARCHIVE_SHA256: 1db18b5e76fa645a7f3865773139bdec8e2d46adbdbb35e7410b34fa8015ccd2"
        in install_uv_step
    )
    assert "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/" in install_uv_step
    assert "--retry 5 --retry-all-errors" in install_uv_step
    assert "sha256sum --check --strict" in install_uv_step
