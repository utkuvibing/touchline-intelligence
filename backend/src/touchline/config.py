"""Typed application settings.

Configuration reaches the application through environment variables only. Nothing is read from a
hard-coded path and no default carries a real credential, so the same image runs locally and on the
deployment target with different values.
"""

from __future__ import annotations

from pydantic import Field, PostgresDsn
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


def get_settings() -> Settings:
    """Build settings from the environment.

    Deliberately not cached: tests construct settings with different environments, and the cost of
    reading a handful of environment variables is irrelevant next to a request.
    """
    return Settings()  # type: ignore[call-arg]  # values come from the environment
