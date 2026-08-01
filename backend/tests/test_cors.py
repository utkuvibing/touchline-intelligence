"""CORS allow-list contract.

No database needed: these exercise the middleware, which is configured from settings when the
module is imported. That import-time read is why each test reloads `touchline.main` with a
patched environment rather than mutating settings afterwards.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import touchline.main
from touchline.config import Settings

ALLOWED = "https://touchline-intelligence.vercel.app"
OTHER = "https://not-our-frontend.example.com"


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in [key for key in os.environ if key.startswith("TOUCHLINE_")]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TOUCHLINE_DB_URL", "postgresql://u:p@localhost:5432/db")
    yield


def _client_with_origins(value: str, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TOUCHLINE_CORS_ORIGINS", value)
    importlib.reload(touchline.main)
    return TestClient(touchline.main.app)


def test_default_allows_only_local_development() -> None:
    """A deployment that forgets to set the origin gets localhost, not everything."""
    settings = Settings(_env_file=None, db_url="postgresql://u:p@localhost:5432/db")  # type: ignore[call-arg, arg-type]

    assert settings.allowed_origins == ["http://localhost:3000"]


def test_named_origin_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client_with_origins(ALLOWED, monkeypatch)

    response = client.get("/health", headers={"Origin": ALLOWED})

    assert response.headers.get("access-control-allow-origin") == ALLOWED


def test_other_origins_are_not_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The header's absence is what makes a browser refuse the response."""
    client = _client_with_origins(ALLOWED, monkeypatch)

    response = client.get("/health", headers={"Origin": OTHER})

    assert "access-control-allow-origin" not in response.headers


def test_a_wildcard_is_never_produced(monkeypatch: pytest.MonkeyPatch) -> None:
    """`*` on a public API lets any page on the internet read it from a visitor's browser.

    Naming the one origin that needs access costs a single environment variable, so a wildcard is
    never worth it. This asserts one cannot appear by accident - including via a stray `*` in the
    configured value, which the middleware would otherwise honour.
    """
    client = _client_with_origins(f"{ALLOWED},*", monkeypatch)

    response = client.get("/health", headers={"Origin": OTHER})

    assert response.headers.get("access-control-allow-origin") != "*"


def test_multiple_origins_are_parsed_and_trimmed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Preview deployments mean more than one origin, and a copied value tends to carry spaces."""
    preview = "https://touchline-intelligence-git-main.vercel.app"
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        db_url="postgresql://u:p@localhost:5432/db",  # type: ignore[arg-type]
        cors_origins=f" {ALLOWED} , {preview} ,",
    )

    assert settings.allowed_origins == [ALLOWED, preview]
