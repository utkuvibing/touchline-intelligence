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
