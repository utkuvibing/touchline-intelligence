"""Typed application settings.

Configuration reaches the application through environment variables only. Nothing is read from a
hard-coded path and no default carries a real credential, so the same image runs locally and on the
deployment target with different values.
"""

from __future__ import annotations

import ipaddress
import os
from typing import Any

from pydantic import Field, PostgresDsn, TypeAdapter, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings for the Touchline backend.

    Every field is read from an environment variable prefixed with ``TOUCHLINE_``. A local
    ``.env`` file is loaded when present; it is git-ignored and must never contain production
    values. See ``.env.example`` for the contract.
    """

    model_config = SettingsConfigDict(
        env_prefix="TOUCHLINE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    environment: str = Field(
        default="local",
        description="Deployment environment name, surfaced by /health for debugging.",
    )
    db_url: PostgresDsn = Field(
        description="PostgreSQL connection string. Required — there is no safe default.",
    )
    cors_origins: str = Field(
        default="http://localhost:3000",
        description=(
            "Comma-separated list of browser origins allowed to call this API. The default covers "
            "local development only; a deployment must set its real frontend origin."
        ),
    )
    historical_model_shots_enabled: bool = Field(
        default=False,
        description=(
            "Publication gate for row-level WC2022 model probabilities. Defaults closed and must "
            "not be enabled publicly until the documented StatsBomb/Hudl question is resolved."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _exclude_migration_configuration(cls, values: Any) -> Any:
        """Keep migration-only input out of serving validation and runtime settings."""
        if not isinstance(values, dict):
            return values
        filtered = dict(values)
        filtered.pop("migration_db_url", None)
        filtered.pop("touchline_migration_db_url", None)
        return filtered

    @property
    def allowed_origins(self) -> list[str]:
        """The CORS allow-list, parsed.

        A wildcard is deliberately not supported. `*` on a public API means any page on the
        internet can read it from a visitor's browser, and the cost of naming the one origin that
        needs access is a single environment variable.

        `*` is **dropped rather than honoured**. The middleware would otherwise pass it straight
        through, so a stray asterisk in an environment variable would silently open the API to
        everything. Dropping it fails closed: the frontend's own origin still works if it is also
        listed, and if the value was *only* `*` the allow-list ends up empty and no cross-origin
        request is permitted — visibly broken, which is the safe direction for a security control.
        """
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip() and origin.strip() != "*"
        ]

    @property
    def db_url_str(self) -> str:
        """The DSN as a plain string, which is what psycopg expects."""
        return str(self.db_url)


class MigrationSettings(BaseSettings):
    """Migration-only configuration, loaded only by the migration command path.

    The serving application deliberately does not model this variable. That keeps a missing or
    malformed migration credential from preventing a correctly configured API worker from
    starting; ``migration_database_url`` validates it when a migration is explicitly requested.
    """

    model_config = SettingsConfigDict(
        env_prefix="TOUCHLINE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    migration_db_url: str | None = Field(
        default=None,
        description="Direct PostgreSQL connection string used only for schema migrations.",
    )


class MissingConfigurationError(RuntimeError):
    """A required environment variable is not set.

    Exists to turn a sixty-line pydantic traceback into one actionable line. Pydantic reports the
    *field* name (`db_url`); an operator looking at a deployment platform needs the *variable*
    name (`TOUCHLINE_DB_URL`), and nothing in the default message bridges the two.
    """


class DirectDatabaseUrlRequiredError(RuntimeError):
    """A write-heavy operator command was given Neon's transaction-pooled endpoint."""


class MigrationDatabaseUrlRequiredError(RuntimeError):
    """A migration run lacks the dedicated direct URL required by its environment."""


class MigrationDatabaseUrlInvalidError(RuntimeError):
    """The dedicated migration URL is malformed and must not be echoed in operator output."""


class RuntimeDatabaseUrlInvalidError(RuntimeError):
    """The runtime database URL is malformed and must not be echoed in operator output."""


def require_direct_database_url(
    db_url: PostgresDsn, *, variable_name: str = "TOUCHLINE_DB_URL"
) -> None:
    """Reject Neon's known ``-pooler`` host without exposing any DSN credentials."""
    for authority in db_url.hosts():
        host = authority.get("host")
        if not isinstance(host, str):
            continue
        normalized = host.rstrip(".").lower()
        first_label = normalized.partition(".")[0]
        if normalized.endswith(".neon.tech") and first_label.endswith("-pooler"):
            remediation = (
                "Set TOUCHLINE_MIGRATION_DB_URL to Neon's direct URL and keep TOUCHLINE_DB_URL "
                "as the pooled URL used by the Railway API."
                if variable_name == "TOUCHLINE_MIGRATION_DB_URL"
                else "Set TOUCHLINE_DB_URL to Neon's direct URL for this local/test migration."
            )
            raise DirectDatabaseUrlRequiredError(
                f"This command requires a direct Neon URL; {variable_name} currently "
                f"uses a pooled '-pooler' hostname. {remediation}"
            )


def migration_database_url(settings: Settings) -> PostgresDsn:
    """Select the migration endpoint while preserving pooled runtime traffic.

    A deployed service must explicitly provide a direct URL. The fallback exists only for local
    development and tests, where one Docker Compose connection is intentionally sufficient.
    """
    raw_migration_url = MigrationSettings().migration_db_url
    if raw_migration_url is not None:
        try:
            return TypeAdapter(PostgresDsn).validate_python(raw_migration_url)
        except ValidationError:
            raise MigrationDatabaseUrlInvalidError(
                "TOUCHLINE_MIGRATION_DB_URL must be a valid PostgreSQL connection URL. "
                "Configure Neon's direct connection URL for migrations."
            ) from None
    environment = settings.environment.strip().lower()
    if environment in {"local", "test"} and is_local_write_target(settings.db_url):
        return settings.db_url
    raise MigrationDatabaseUrlRequiredError(
        "TOUCHLINE_MIGRATION_DB_URL is required unless this is a local/test environment and "
        "TOUCHLINE_DB_URL points to a local database. Configure Neon's direct connection URL for "
        "migrations; TOUCHLINE_DB_URL remains the pooled runtime URL."
    )


def migration_uses_dedicated_url() -> bool:
    """Whether the migration-only variable is configured, without validating its value."""
    return MigrationSettings().migration_db_url is not None


class RemoteWriteBlockedError(RuntimeError):
    """A data-mutating command was pointed at a database that is not local.

    The accident this exists for is mundane and entirely silent: ``.env`` holds a deployment DSN
    for some legitimate reason, a developer runs ``uv run poe ingest`` expecting the Docker Compose
    database, and the loader happily rewrites the deployed one instead. Nothing in the command name
    or its output distinguishes the two beforehand.
    """


#: Environment variable that unlocks one data-mutating run against a non-local database.
#:
#: Its value must be the exact sanitized write target, e.g.
#: ``TOUCHLINE_ALLOW_REMOTE_WRITES='db.example.com/touchline'``. Naming the target is the point:
#: a generic ``1`` or ``true`` can be left exported from an unrelated experiment and would then
#: silently disarm the guard for every later command, whereas a value that spells out one specific
#: database cannot be reused by accident against a different one.
REMOTE_WRITE_OVERRIDE_VAR = "TOUCHLINE_ALLOW_REMOTE_WRITES"

#: Hostnames treated as local. Loopback *addresses* are recognised by range rather than by literal,
#: so 127.0.0.2 is local too; `0.0.0.0` deliberately is not, because as a client target it is
#: ambiguous and this guard resolves ambiguity by refusing.
_LOCAL_HOSTNAMES = frozenset({"localhost"})


def write_target(db_url: PostgresDsn) -> str:
    """A stable ``host[:port]/database`` label for a DSN, safe to print.

    Built only from the host, port and path. The username, password and any query parameters —
    which is where Neon and other managed providers put credentials and endpoint tokens — are
    never read, so no caller of this function can leak one into a log, an exception or a report.

    A DSN with no usable host yields ``"<unknown>"`` rather than raising, because the callers below
    treat an unclassifiable target as remote and need something to name in the refusal.
    """
    hosts = db_url.hosts()
    host = hosts[0].get("host") if hosts else None
    if not isinstance(host, str) or not host:
        return "<unknown>"
    label = host.rstrip(".").lower()
    port = hosts[0].get("port") if hosts else None
    if port is not None:
        label = f"{label}:{port}"
    database = (db_url.path or "").lstrip("/")
    return f"{label}/{database}" if database else label


def is_local_write_target(db_url: PostgresDsn) -> bool:
    """Whether the DSN points at a PostgreSQL running on this machine.

    Classification comes from the DSN itself, never from ``TOUCHLINE_ENVIRONMENT``. That label is
    a free-text field surfaced by ``/health``; it can say ``local`` while the DSN points at a
    managed deployment, and in this repository it once did. A safety control that trusts a
    self-declared label protects nothing at the moment the label is the thing that is wrong.

    Anything unrecognised — an unparseable host, an empty DSN, a name this function has never seen
    — is **not** local. The classification fails closed so that a new deployment topology has to be
    admitted deliberately rather than inheriting a permission by omission.
    """
    hosts = db_url.hosts()
    host = hosts[0].get("host") if hosts else None
    if not isinstance(host, str) or not host:
        return False
    normalized = host.rstrip(".").lower()
    if normalized in _LOCAL_HOSTNAMES or normalized.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(normalized.strip("[]")).is_loopback
    except ValueError:
        return False


def require_local_write_target(db_url: PostgresDsn, *, command: str) -> None:
    """Refuse a data-mutating command against a non-local database.

    The single enforcement point for every write workflow, rather than a check per command: a
    scattered version protects only the commands somebody remembered, and the next one added is
    unprotected by default. Here the default is refusal.

    Read-only workflows do not call this. ``poe quality``, the WP1.5/WP2.1/WP2.2 analysis queries
    and the deployed smoke checks are expected to run against a deployment and are unaffected.

    Schema migration is also deliberately outside this guard. Applying ordered migrations to the
    deployed database is a deliberate operator step run on its own, it changes structure
    rather than application data, and folding it in here as a side effect of protecting ingestion
    would break the release runbook without anyone having decided to. It is assessed on its own
    terms; see the note in that document.

    Raises:
        RemoteWriteBlockedError: unless the target is local, or ``TOUCHLINE_ALLOW_REMOTE_WRITES``
            names exactly this target.
    """
    if is_local_write_target(db_url):
        return

    target = write_target(db_url)
    if os.environ.get(REMOTE_WRITE_OVERRIDE_VAR, "").strip() == target:
        return

    raise RemoteWriteBlockedError(
        f"Refusing to run '{command}' against the non-local database {target}.\n"
        f"This command writes application data, and TOUCHLINE_DB_URL does not point at a local "
        f"PostgreSQL instance. Local development should use the Docker Compose database on "
        f"localhost:5433 (see infra/docker-compose.yml).\n"
        f"If writing to {target} is genuinely intended, name it for this one run:\n"
        f"    {REMOTE_WRITE_OVERRIDE_VAR}='{target}' uv run poe {command}\n"
        f"The variable must equal that target exactly; a generic value such as '1' or 'true' is "
        f"not accepted."
    )


def get_settings() -> Settings:
    """Build settings from the environment.

    Deliberately not cached: tests construct settings with different environments, and the cost of
    reading a handful of environment variables is irrelevant next to a request.

    Missing configuration still fails at startup rather than being defaulted away — an instance
    that boots with no database configured and reports itself healthy is worse than one that
    refuses to boot. Only the error message improves here, not the behaviour.
    """
    try:
        return Settings()  # type: ignore[call-arg]  # values come from the environment
    except ValidationError as exc:
        errors = exc.errors()
        if any(error["loc"] == ("db_url",) and error["type"] != "missing" for error in errors):
            raise RuntimeDatabaseUrlInvalidError(
                "TOUCHLINE_DB_URL must be a valid PostgreSQL connection URL. Configure Neon's "
                "pooled connection URL for the serving API."
            ) from None
        missing = [
            f"{Settings.model_config['env_prefix']}{error['loc'][0]}".upper()
            for error in errors
            if error["type"] == "missing" and error["loc"]
        ]
        if not missing:
            raise
        raise MissingConfigurationError(
            f"Missing required environment variable(s): {', '.join(missing)}. "
            "Set them in the deployment platform's variables, or copy .env.example to .env "
            "for local development. See README.md."
        ) from None
