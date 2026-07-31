"""Settings contract tests.

These protect two rules that are easy to break silently and expensive to discover in production:
a missing database URL must fail loudly, and an unrecognised setting must not be ignored.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from touchline.config import Settings

VALID_DSN = "postgresql://touchline:localdev@localhost:5432/touchline"


def _settings(**env: str) -> Settings:
    """Build Settings from an explicit environment, ignoring any local .env file.

    `_env_file=None` is a pydantic-settings runtime option rather than a declared field, so it is
    invisible to the type checker; the ignore is narrow and deliberate. Without it these tests
    would pass or fail depending on whether the developer happens to have a .env file.
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
