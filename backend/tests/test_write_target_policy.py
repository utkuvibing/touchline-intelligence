"""Executable contract for the data-mutating write-target guard.

The accident being prevented is specific: `.env` holds a deployment DSN, a developer runs
`uv run poe ingest` expecting the Docker Compose database, and the loader rewrites the deployed one
instead. Nothing in the command or its output distinguishes the two beforehand, so the guard has to.

No database and no network: every test here drives the classification and the CLI boundary with
synthetic DSNs.
"""

from __future__ import annotations

from typing import cast

import pytest
from pydantic import PostgresDsn

from touchline.config import (
    REMOTE_WRITE_OVERRIDE_VAR,
    RemoteWriteBlockedError,
    Settings,
    is_local_write_target,
    require_local_write_target,
    write_target,
)
from touchline.ingest import cli, migrate

PASSWORD = "super-secret-do-not-print"

LOCAL_DSN = f"postgresql://touchline:{PASSWORD}@localhost:5433/touchline"
LOCAL_IP_DSN = f"postgresql://touchline:{PASSWORD}@127.0.0.1:5433/touchline"
PRODUCTION_DSN = (
    f"postgresql://neondb_owner:{PASSWORD}@"
    "ep-example-endpoint.eu-central-1.aws.neon.tech/neondb?sslmode=require"
)
PRODUCTION_TARGET = "ep-example-endpoint.eu-central-1.aws.neon.tech/neondb"
STAGING_DSN = f"postgresql://touchline:{PASSWORD}@db.staging.internal:5432/touchline_staging"
STAGING_TARGET = "db.staging.internal:5432/touchline_staging"


def settings_for(dsn: str) -> Settings:
    return Settings(_env_file=None, db_url=dsn)  # type: ignore[call-arg, arg-type]


def _unexpected_work(*args: object, **kwargs: object) -> None:
    del args, kwargs
    pytest.fail("the write-target guard must run before any database or source work")


@pytest.fixture(autouse=True)
def _no_inherited_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stray override in the developer's own shell must not decide these results."""
    monkeypatch.delenv(REMOTE_WRITE_OVERRIDE_VAR, raising=False)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dsn",
    [
        LOCAL_DSN,
        LOCAL_IP_DSN,
        f"postgresql://u:{PASSWORD}@127.0.0.2:5432/touchline",
        f"postgresql://u:{PASSWORD}@[::1]:5432/touchline",
        f"postgresql://u:{PASSWORD}@touchline.localhost:5433/touchline",
    ],
)
def test_local_targets_are_recognised(dsn: str) -> None:
    """Loopback is recognised by address range, not by matching the literal 127.0.0.1."""
    assert is_local_write_target(settings_for(dsn).db_url) is True


@pytest.mark.parametrize(
    "dsn",
    [
        PRODUCTION_DSN,
        STAGING_DSN,
        f"postgresql://u:{PASSWORD}@10.0.0.5:5432/touchline",
        f"postgresql://u:{PASSWORD}@db.example.com/touchline",
        # Ambiguous rather than clearly local: a bind address, not a client target.
        f"postgresql://u:{PASSWORD}@0.0.0.0:5432/touchline",
        # Superficially reassuring, actually a remote domain.
        f"postgresql://u:{PASSWORD}@localhost.evil.example.com/touchline",
    ],
)
def test_unrecognised_and_remote_targets_are_not_local(dsn: str) -> None:
    """Classification fails closed: anything not provably local is treated as remote."""
    assert is_local_write_target(settings_for(dsn).db_url) is False


class _HostlessDsn:
    """A DSN shape `PostgresDsn` validation currently forbids.

    Every string form of a hostless PostgreSQL URL is rejected by pydantic today, so the guard's
    "no usable host" branch cannot be reached through `Settings`. It is kept anyway, and tested
    here through the same public functions: without it, a future pydantic release or a multi-host
    DSN that yields no host would make classification raise `IndexError` instead of failing closed
    — the one direction a safety control must never fail. This stub exists to make that branch
    observable, not to model a DSN the application accepts.
    """

    path = "/touchline"

    def hosts(self) -> list[dict[str, object]]:
        return [{"host": None}]


def test_a_dsn_with_no_usable_host_fails_closed() -> None:
    dsn = cast(PostgresDsn, _HostlessDsn())
    assert is_local_write_target(dsn) is False
    assert write_target(dsn) == "<unknown>"
    with pytest.raises(RemoteWriteBlockedError, match="<unknown>"):
        require_local_write_target(dsn, command="ingest")


def test_an_empty_host_list_fails_closed() -> None:
    class _NoHosts(_HostlessDsn):
        def hosts(self) -> list[dict[str, object]]:
            return []

    dsn = cast(PostgresDsn, _NoHosts())
    assert is_local_write_target(dsn) is False
    with pytest.raises(RemoteWriteBlockedError):
        require_local_write_target(dsn, command="ingest")


def test_environment_label_cannot_reclassify_a_remote_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact shape of the real accident: a `local` label in front of a deployment DSN.

    Classification is derived from the DSN, so a stale or wrong `TOUCHLINE_ENVIRONMENT` cannot
    unlock anything. A control that trusted the label would fail precisely when the label is the
    thing that is wrong.
    """
    monkeypatch.setenv("TOUCHLINE_ENVIRONMENT", "local")
    settings = Settings(_env_file=None, db_url=PRODUCTION_DSN)  # type: ignore[call-arg, arg-type]
    assert settings.environment == "local"
    assert is_local_write_target(settings.db_url) is False
    with pytest.raises(RemoteWriteBlockedError):
        require_local_write_target(settings.db_url, command="ingest")


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


def test_local_writes_are_permitted() -> None:
    require_local_write_target(settings_for(LOCAL_DSN).db_url, command="ingest")


def test_production_target_is_rejected_by_default() -> None:
    with pytest.raises(RemoteWriteBlockedError) as excinfo:
        require_local_write_target(settings_for(PRODUCTION_DSN).db_url, command="ingest")
    assert PRODUCTION_TARGET in str(excinfo.value)


def test_non_production_remote_target_follows_the_same_policy() -> None:
    """Staging is remote, so it is refused by default and unlocked the same deliberate way.

    One rule rather than a production allow-list: a list has to be maintained, and the run that
    hurts is the one against a host nobody thought to add to it.
    """
    dsn = settings_for(STAGING_DSN).db_url
    with pytest.raises(RemoteWriteBlockedError):
        require_local_write_target(dsn, command="ingest")


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", "*", "all", ""])
def test_generic_truthy_overrides_are_refused(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """A value that could be left exported from an unrelated experiment must not disarm anything."""
    monkeypatch.setenv(REMOTE_WRITE_OVERRIDE_VAR, value)
    with pytest.raises(RemoteWriteBlockedError):
        require_local_write_target(settings_for(PRODUCTION_DSN).db_url, command="ingest")


def test_override_naming_a_different_target_does_not_unlock_this_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An override left over from a legitimate staging run must not authorise production."""
    monkeypatch.setenv(REMOTE_WRITE_OVERRIDE_VAR, STAGING_TARGET)
    with pytest.raises(RemoteWriteBlockedError):
        require_local_write_target(settings_for(PRODUCTION_DSN).db_url, command="ingest")


@pytest.mark.parametrize(
    ("dsn", "target"),
    [(PRODUCTION_DSN, PRODUCTION_TARGET), (STAGING_DSN, STAGING_TARGET)],
)
def test_exact_override_permits_the_intended_target(
    monkeypatch: pytest.MonkeyPatch, dsn: str, target: str
) -> None:
    monkeypatch.setenv(REMOTE_WRITE_OVERRIDE_VAR, target)
    require_local_write_target(settings_for(dsn).db_url, command="ingest")


def test_setting_the_override_does_not_break_settings_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The override is a bare environment variable, not a `Settings` field, and must stay one.

    `Settings` forbids extra fields, so if the override were ever declared there — or if the
    settings sources changed to reject unmatched `TOUCHLINE_*` variables — supplying it would crash
    the command it exists to unlock. It is also not configuration: it authorises one run, and a
    `Settings` field invites someone to park it in `.env`, which is exactly the standing permission
    this guard refuses to grant.
    """
    from touchline.config import get_settings

    monkeypatch.setenv(REMOTE_WRITE_OVERRIDE_VAR, PRODUCTION_TARGET)
    monkeypatch.setenv("TOUCHLINE_DB_URL", LOCAL_DSN)
    assert get_settings().db_url_str.startswith("postgresql://")


def test_override_tolerates_only_surrounding_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REMOTE_WRITE_OVERRIDE_VAR, f"  {PRODUCTION_TARGET}  ")
    require_local_write_target(settings_for(PRODUCTION_DSN).db_url, command="ingest")

    monkeypatch.setenv(REMOTE_WRITE_OVERRIDE_VAR, PRODUCTION_TARGET.replace("/", " /"))
    with pytest.raises(RemoteWriteBlockedError):
        require_local_write_target(settings_for(PRODUCTION_DSN).db_url, command="ingest")


# ---------------------------------------------------------------------------
# Credential hygiene
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dsn", [PRODUCTION_DSN, STAGING_DSN])
def test_the_sanitized_target_omits_credentials_and_query_parameters(dsn: str) -> None:
    target = write_target(settings_for(dsn).db_url)
    assert PASSWORD not in target
    assert "neondb_owner" not in target
    assert "sslmode" not in target
    assert "@" not in target
    assert "?" not in target


def test_refusal_text_names_the_database_without_leaking_the_dsn() -> None:
    with pytest.raises(RemoteWriteBlockedError) as excinfo:
        require_local_write_target(settings_for(PRODUCTION_DSN).db_url, command="ingest")
    message = str(excinfo.value)

    assert PRODUCTION_TARGET in message
    assert REMOTE_WRITE_OVERRIDE_VAR in message
    assert PASSWORD not in message
    assert "neondb_owner" not in message
    assert PRODUCTION_DSN not in message
    assert "sslmode" not in message


def test_an_unclassifiable_target_is_refused_and_named_safely() -> None:
    """A DSN this guard cannot classify is refused, and the refusal still prints no credentials."""
    dsn = settings_for(f"postgresql://u:{PASSWORD}@db.example.com/touchline").db_url
    with pytest.raises(RemoteWriteBlockedError) as excinfo:
        require_local_write_target(dsn, command="ingest")
    assert PASSWORD not in str(excinfo.value)


# ---------------------------------------------------------------------------
# Command boundary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("argv", [[], ["--reset"], ["--offline"], ["--reset", "--offline"]])
def test_ingest_refuses_a_production_target_before_any_work(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    """`--reset` needs no separate rule: it is strictly more destructive than a plain load."""
    monkeypatch.setenv("TOUCHLINE_DB_URL", PRODUCTION_DSN)
    monkeypatch.setattr("psycopg.connect", _unexpected_work)
    monkeypatch.setattr(cli, "StatsBombSource", _unexpected_work)

    assert cli.main(argv) == 1

    error = capsys.readouterr().err
    assert "Refusing to run 'ingest'" in error
    assert PRODUCTION_TARGET in error
    assert PASSWORD not in error
    assert PRODUCTION_DSN not in error


def test_ingest_runs_against_a_local_target(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard must be invisible to ordinary local development.

    Proven by letting the command past the guard and failing at the first real step instead: a
    still-blocking guard would return 1 without ever reaching the connection.
    """
    monkeypatch.setenv("TOUCHLINE_DB_URL", LOCAL_DSN)
    reached: list[str] = []

    def _record_connection(*args: object, **kwargs: object) -> None:
        del args, kwargs
        reached.append("connect")
        raise RuntimeError("stop after the guard")

    monkeypatch.setattr("psycopg.connect", _record_connection)
    with pytest.raises(RuntimeError, match="stop after the guard"):
        cli.main(["--offline"])
    assert reached == ["connect"]


def test_migration_is_deliberately_outside_the_write_target_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Applying migrations to a deployment is a documented operator step, not an accident path.

    Recorded as an executable decision rather than left implicit: migration changes structure, not
    application data, and the operator release runbook depends on being able to run it against
    Neon. If the guard is ever extended to cover migration, this test fails and the runbook gets
    revisited with it instead of breaking silently in a release.
    """
    monkeypatch.setenv("TOUCHLINE_DB_URL", PRODUCTION_DSN)
    reached: list[str] = []

    def _record_connection(*args: object, **kwargs: object) -> None:
        del args, kwargs
        reached.append("connect")
        raise RuntimeError("stop after the guard")

    monkeypatch.setattr("psycopg.connect", _record_connection)
    with pytest.raises(RuntimeError, match="stop after the guard"):
        migrate.main()
    assert reached == ["connect"]


def test_read_only_quality_command_is_unaffected(monkeypatch: pytest.MonkeyPatch) -> None:
    """`poe quality` audits a deployment without writing, so the guard must not reach it."""
    from touchline import quality_cli

    monkeypatch.setenv("TOUCHLINE_DB_URL", PRODUCTION_DSN)
    reached: list[str] = []

    def _record_connection(*args: object, **kwargs: object) -> None:
        del args, kwargs
        reached.append("connect")
        raise RuntimeError("stop after the guard")

    monkeypatch.setattr("psycopg.connect", _record_connection)
    assert quality_cli.main([]) == 1
    assert reached == ["connect"]
