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

from touchline.config import (
    MigrationDatabaseUrlInvalidError,
    MigrationDatabaseUrlRequiredError,
    MissingConfigurationError,
    RuntimeDatabaseUrlInvalidError,
    Settings,
    get_settings,
    migration_database_url,
)

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


@pytest.mark.parametrize("environment", ["local", "test", "LOCAL", " Test "])
def test_local_and_test_migrations_may_fall_back_to_runtime_url(environment: str) -> None:
    settings = _settings(db_url=VALID_DSN, environment=environment)
    assert migration_database_url(settings) == settings.db_url


def test_default_environment_may_fall_back_only_for_a_local_database() -> None:
    settings = _settings(db_url=VALID_DSN)
    assert migration_database_url(settings) == settings.db_url


def test_unlabelled_remote_database_cannot_use_the_local_default_as_migration_authority() -> None:
    settings = _settings(db_url="postgresql://operator:secret@db.example.test:5432/touchline")

    with pytest.raises(MigrationDatabaseUrlRequiredError) as excinfo:
        migration_database_url(settings)

    assert "TOUCHLINE_MIGRATION_DB_URL" in str(excinfo.value)
    assert "secret" not in str(excinfo.value)


@pytest.mark.parametrize("environment", ["local", "test"])
def test_local_label_cannot_authorize_remote_migration_fallback(environment: str) -> None:
    settings = _settings(
        db_url="postgresql://operator:secret@db.example.test:5432/touchline",
        environment=environment,
    )

    with pytest.raises(MigrationDatabaseUrlRequiredError):
        migration_database_url(settings)


@pytest.mark.parametrize("environment", ["production", "staging", "preview"])
def test_non_local_migrations_require_a_dedicated_url_without_leaking_runtime_dsn(
    environment: str,
) -> None:
    runtime_dsn = "postgresql://operator:secret@db.example.test:5432/touchline"
    settings = _settings(db_url=runtime_dsn, environment=environment)

    with pytest.raises(MigrationDatabaseUrlRequiredError) as excinfo:
        migration_database_url(settings)

    message = str(excinfo.value)
    assert "TOUCHLINE_MIGRATION_DB_URL" in message
    assert "secret" not in message
    assert runtime_dsn not in message


def test_migration_url_is_independent_of_the_pooled_runtime_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_dsn = "postgresql://operator:secret@direct.example.test:5432/touchline"
    monkeypatch.setenv("TOUCHLINE_MIGRATION_DB_URL", migration_dsn)
    settings = _settings(
        db_url="postgresql://operator:secret@pooled.example.test:5432/touchline",
        environment="production",
    )
    assert str(migration_database_url(settings)) == migration_dsn


def test_invalid_migration_url_does_not_break_serving_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    secret = "not-a-dsn-with-secret"
    monkeypatch.setenv("TOUCHLINE_DB_URL", VALID_DSN)
    monkeypatch.setenv("TOUCHLINE_MIGRATION_DB_URL", secret)

    settings = get_settings()
    assert settings.db_url_str == VALID_DSN

    with pytest.raises(MigrationDatabaseUrlInvalidError) as excinfo:
        migration_database_url(settings)

    message = str(excinfo.value)
    assert "TOUCHLINE_MIGRATION_DB_URL" in message
    assert secret not in message


def test_invalid_migration_url_does_not_mask_missing_runtime_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    secret = "postgresql://operator:credential@not a valid host/touchline"
    monkeypatch.setenv("TOUCHLINE_MIGRATION_DB_URL", secret)

    with pytest.raises(MissingConfigurationError) as excinfo:
        get_settings()

    assert "TOUCHLINE_DB_URL" in str(excinfo.value)
    assert secret not in str(excinfo.value)


def test_missing_migration_url_does_not_break_serving_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TOUCHLINE_DB_URL", VALID_DSN)
    monkeypatch.delenv("TOUCHLINE_MIGRATION_DB_URL", raising=False)

    settings = get_settings()

    assert settings.db_url_str == VALID_DSN


def test_malformed_migration_url_in_dotenv_does_not_break_serving_settings(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"TOUCHLINE_DB_URL={VALID_DSN}\nTOUCHLINE_MIGRATION_DB_URL=not-a-dsn\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)  # type: ignore[call-arg]

    assert settings.db_url_str == VALID_DSN


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


def test_a_present_but_invalid_runtime_url_has_a_sanitized_unchained_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    secret = "postgresql://runtime:credential@not a valid host/touchline"
    monkeypatch.setenv("TOUCHLINE_DB_URL", secret)

    with pytest.raises(RuntimeDatabaseUrlInvalidError) as excinfo:
        get_settings()

    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__ is True
    assert secret not in str(excinfo.value)
    assert "TOUCHLINE_DB_URL" in str(excinfo.value)
