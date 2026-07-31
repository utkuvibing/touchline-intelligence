"""Settings contract tests.

These protect two rules that are easy to break silently and expensive to discover in production:
a missing database URL must fail loudly, and an unrecognised setting must not be ignored.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from pydantic import ValidationError

from touchline.config import Settings

VALID_DSN = "postgresql://touchline:localdev@localhost:5432/touchline"


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Remove every TOUCHLINE_* variable from the real process environment.

    Settings reads two sources: a .env file and the actual environment. `_env_file=None` silences
    only the first. Without this fixture, `test_db_url_is_required` passes on a developer machine
    with nothing exported and fails wherever TOUCHLINE_DB_URL happens to be set - which is exactly
    what CI does now that it runs the ingestion tests against a service container.

    The test was environment-dependent before CI exposed it. A test whose result depends on the
    shell it runs in is not asserting what it claims to.
    """
    for name in [key for key in os.environ if key.startswith("TOUCHLINE_")]:
        monkeypatch.delenv(name, raising=False)
    yield


def _settings(**env: str) -> Settings:
    """Build Settings from an explicit environment, ignoring any local .env file.

    `_env_file=None` is a pydantic-settings runtime option rather than a declared field, so it is
    invisible to the type checker; the ignore is narrow and deliberate.
    """
    return Settings(_env_file=None, **env)  # type: ignore[call-arg, arg-type]


def test_db_url_is_required() -> None:
    """There is no default database URL.

    A default would let a misconfigured deployment start and quietly talk to the wrong database,
    or to nothing at all. Failing at startup is the cheapest place to find this.
    """
    with pytest.raises(ValidationError) as exc:
        _settings()
    assert "db_url" in str(exc.value)


def test_db_url_must_be_a_postgres_dsn() -> None:
    """A malformed or non-PostgreSQL URL is rejected at construction, not at first query."""
    with pytest.raises(ValidationError):
        _settings(db_url="not-a-dsn")


def test_environment_defaults_to_local() -> None:
    """The environment label is safe to default; only credentials are not."""
    settings = _settings(db_url=VALID_DSN)
    assert settings.environment == "local"


def test_unknown_settings_are_rejected() -> None:
    """`extra="forbid"` turns a typo into a startup failure instead of a silently ignored value.

    Without this, `TOUCHLINE_DB_URI=...` would be accepted and ignored while `db_url` stayed unset.
    """
    with pytest.raises(ValidationError):
        _settings(db_url=VALID_DSN, unexpected_setting="x")


def test_db_url_str_round_trips() -> None:
    """psycopg needs a plain string; the DSN must survive validation unchanged."""
    settings = _settings(db_url=VALID_DSN)
    assert settings.db_url_str.startswith("postgresql://")
    assert "localhost:5432" in settings.db_url_str
