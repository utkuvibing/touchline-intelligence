"""Settings contract tests.

These protect two rules that are easy to break silently and expensive to discover in production:
a missing database URL must fail loudly, and an unrecognised setting must not be ignored.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import ValidationError

from touchline.config import MissingConfigurationError, Settings, get_settings

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


def test_missing_variable_error_names_the_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The message must name TOUCHLINE_DB_URL, not the field `db_url`.

    Written after a real deployment failure: Railway showed sixty lines of pydantic traceback
    ending in "db_url Field required", and nothing in it said which variable to set. An operator
    reading a platform's log needs the variable name, not the model's field name.

    Runs from an empty directory so the repository's own .env cannot satisfy the setting - which
    is exactly the situation in a container, where there is no .env at all.
    """
    monkeypatch.chdir(tmp_path)

    with pytest.raises(MissingConfigurationError) as exc:
        get_settings()

    message = str(exc.value)
    assert "TOUCHLINE_DB_URL" in message
    assert "README.md" in message


def test_a_present_but_invalid_value_still_raises_the_validation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only *missing* configuration gets the friendlier message.

    A malformed DSN is a different mistake, pydantic already explains it well, and folding it into
    a "missing variable" message would send the reader looking for a variable that is right there.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TOUCHLINE_DB_URL", "not-a-dsn")

    with pytest.raises(ValidationError):
        get_settings()
