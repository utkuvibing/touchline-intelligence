"""Database-endpoint policy at migration and ingestion command boundaries."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest

from touchline.config import (
    REMOTE_WRITE_OVERRIDE_VAR,
    DirectDatabaseUrlRequiredError,
    Settings,
    require_direct_database_url,
)
from touchline.ingest import cli, migrate

POOLED_DSN = (
    "postgresql://operator:super-secret@"
    "ep-touchline-pooler.eu-central-1.aws.neon.tech/touchline?sslmode=require"
)
DIRECT_DSN = (
    "postgresql://operator:super-secret@"
    "ep-touchline.eu-central-1.aws.neon.tech/touchline?sslmode=require"
)
POOLED_TARGET = "ep-touchline-pooler.eu-central-1.aws.neon.tech/touchline"


def _unexpected_work(*args: object, **kwargs: object) -> None:
    del args, kwargs
    pytest.fail("the pooled-URL policy must run before database or source work")


def test_pooled_url_remains_valid_api_configuration() -> None:
    """The endpoint policy belongs to operator commands, not shared application settings."""
    settings = Settings(_env_file=None, db_url=POOLED_DSN)  # type: ignore[call-arg, arg-type]
    assert "-pooler" in settings.db_url_str


def test_direct_neon_url_is_accepted_for_operator_commands() -> None:
    settings = Settings(_env_file=None, db_url=DIRECT_DSN)  # type: ignore[call-arg, arg-type]
    require_direct_database_url(settings.db_url)


def test_migration_pooler_error_names_the_dedicated_variable_without_leaking_the_dsn() -> None:
    pooled = Settings(_env_file=None, db_url=POOLED_DSN)  # type: ignore[call-arg, arg-type]
    with pytest.raises(DirectDatabaseUrlRequiredError) as excinfo:
        require_direct_database_url(
            pooled.db_url,
            variable_name="TOUCHLINE_MIGRATION_DB_URL",
        )
    message = str(excinfo.value)
    assert "TOUCHLINE_MIGRATION_DB_URL" in message
    assert "super-secret" not in message
    assert POOLED_DSN not in message


def test_production_migration_requires_dedicated_url_before_database_work(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TOUCHLINE_ENVIRONMENT", "production")
    monkeypatch.setenv("TOUCHLINE_DB_URL", DIRECT_DSN)
    monkeypatch.setattr("psycopg.connect", _unexpected_work)

    assert migrate.main() == 1

    error = capsys.readouterr().err
    assert "TOUCHLINE_MIGRATION_DB_URL" in error
    assert "super-secret" not in error
    assert DIRECT_DSN not in error


def test_migration_rejects_an_invalid_dedicated_url_without_echoing_it(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "not-a-dsn-with-secret"
    monkeypatch.setenv("TOUCHLINE_DB_URL", DIRECT_DSN)
    monkeypatch.setenv("TOUCHLINE_MIGRATION_DB_URL", secret)
    monkeypatch.setattr("psycopg.connect", _unexpected_work)

    assert migrate.main() == 1

    error = capsys.readouterr().err
    assert "TOUCHLINE_MIGRATION_DB_URL" in error
    assert secret not in error


def test_migration_cli_sanitizes_invalid_dedicated_url_even_when_runtime_url_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    secret = "postgresql://operator:credential@not a valid host/touchline"
    monkeypatch.delenv("TOUCHLINE_DB_URL", raising=False)
    monkeypatch.setenv("TOUCHLINE_MIGRATION_DB_URL", secret)
    monkeypatch.setattr("psycopg.connect", _unexpected_work)

    assert migrate.main() == 1

    error = capsys.readouterr().err
    assert error.startswith("TOUCHLINE_MIGRATION_DB_URL must be a valid")
    assert secret not in error


def test_migration_cli_sanitizes_invalid_runtime_url_with_valid_direct_migration_url(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    secret = "postgresql://runtime:credential@not a valid host/touchline"
    monkeypatch.setenv("TOUCHLINE_ENVIRONMENT", "production")
    monkeypatch.setenv("TOUCHLINE_DB_URL", secret)
    monkeypatch.setenv("TOUCHLINE_MIGRATION_DB_URL", DIRECT_DSN)
    monkeypatch.setattr("psycopg.connect", _unexpected_work)

    assert migrate.main() == 1

    error = capsys.readouterr().err
    assert error.startswith("TOUCHLINE_DB_URL must be a valid")
    assert secret not in error
    assert "Traceback" not in error


def test_migration_cli_reports_missing_runtime_configuration_safely(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TOUCHLINE_DB_URL", raising=False)
    monkeypatch.delenv("TOUCHLINE_MIGRATION_DB_URL", raising=False)
    monkeypatch.setattr("psycopg.connect", _unexpected_work)

    assert migrate.main() == 1

    error = capsys.readouterr().err
    assert "TOUCHLINE_DB_URL" in error
    assert "Traceback" not in error


def test_production_migration_uses_dedicated_direct_url_not_runtime_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Connection:
        def __enter__(self) -> _Connection:
            return self

        def __exit__(self, *args: object) -> None:
            del args

    connected_to: list[str] = []

    def _connect(dsn: str) -> _Connection:
        connected_to.append(dsn)
        return _Connection()

    monkeypatch.setenv("TOUCHLINE_ENVIRONMENT", "production")
    monkeypatch.setenv("TOUCHLINE_DB_URL", POOLED_DSN)
    monkeypatch.setenv("TOUCHLINE_MIGRATION_DB_URL", DIRECT_DSN)
    monkeypatch.setattr("psycopg.connect", _connect)
    monkeypatch.setattr(migrate, "apply_migrations", lambda conn: ())

    assert migrate.main() == 0
    assert connected_to == [DIRECT_DSN]


def test_migration_connection_failure_does_not_echo_driver_detail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TOUCHLINE_ENVIRONMENT", "production")
    monkeypatch.setenv("TOUCHLINE_DB_URL", POOLED_DSN)
    monkeypatch.setenv("TOUCHLINE_MIGRATION_DB_URL", DIRECT_DSN)

    def _connect(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise psycopg.OperationalError(f"connection failed for {DIRECT_DSN}")

    monkeypatch.setattr("psycopg.connect", _connect)

    assert migrate.main() == 1

    error = capsys.readouterr().err
    assert error == "Migration failed: OperationalError\n"
    assert "super-secret" not in error
    assert DIRECT_DSN not in error


@pytest.mark.parametrize(
    ("command", "patch_source"),
    [
        pytest.param(migrate.main, False, id="migration"),
        pytest.param(lambda: cli.main([]), True, id="ingestion"),
    ],
)
def test_operator_commands_reject_neon_pooler_before_any_work(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: Callable[[], int],
    patch_source: bool,
) -> None:
    """The pooled-endpoint policy, isolated from the write-target guard.

    Ingestion now refuses any non-local target first, and a Neon pooler host is non-local, so this
    test would otherwise measure the newer guard instead of the endpoint rule it was written for.
    Supplying the deliberate override reproduces the situation the endpoint rule actually governs:
    an operator who has decided to write to Neon and reached for the wrong endpoint flavour.
    Migration is not covered by the write-target guard, so it needs no override here.
    """
    monkeypatch.setenv("TOUCHLINE_DB_URL", POOLED_DSN)
    if command is migrate.main:
        monkeypatch.setenv("TOUCHLINE_MIGRATION_DB_URL", POOLED_DSN)
    monkeypatch.setenv(REMOTE_WRITE_OVERRIDE_VAR, POOLED_TARGET)
    monkeypatch.setattr("psycopg.connect", _unexpected_work)
    if patch_source:
        monkeypatch.setattr(cli, "StatsBombSource", _unexpected_work)

    assert command() == 1

    error = capsys.readouterr().err
    assert "direct Neon URL" in error
    assert "-pooler" in error
    assert "super-secret" not in error
    assert POOLED_DSN not in error
