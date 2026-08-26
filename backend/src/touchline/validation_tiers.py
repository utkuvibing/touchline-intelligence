"""WP5.4 validation-tier entry points.

This module orchestrates existing checks; it intentionally contains no test, model, data, or
deployment logic.  A tier cannot treat an unavailable prerequisite as a passing skip.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit


class Tier(StrEnum):
    """The three WP5.4 validation decisions."""

    PR = "pr"
    MILESTONE = "milestone"
    RELEASE = "release"


class ValidationPrerequisiteError(RuntimeError):
    """A required tier condition was absent or unsafe."""


class TierUnavailableError(ValidationPrerequisiteError):
    """A planned tier has an intentionally unimplemented mandatory control."""


@dataclass(frozen=True)
class Command:
    """One existing command composed by a validation tier."""

    label: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class TierPlan:
    """The commands and preconditions for one validation decision."""

    tier: Tier
    purpose: str
    commands: tuple[Command, ...]
    required_environment: tuple[str, ...]
    requires_clean_tree: bool = False
    unavailable_reason: str | None = None


PR_COMMANDS = (
    Command("backend code health", ("uv", "run", "poe", "check")),
    Command("frontend lint", ("npm", "--prefix", "frontend", "run", "lint")),
    Command("frontend type check", ("npm", "--prefix", "frontend", "run", "typecheck")),
    Command("frontend tests", ("npm", "--prefix", "frontend", "test")),
)

MILESTONE_COMMANDS = (
    *PR_COMMANDS,
    Command("full-cohort acceptance", ("uv", "run", "pytest", "-m", "full_cohort")),
    Command("fixture reproducibility", ("uv", "run", "poe", "reproducibility-fixture")),
    Command("frontend production build", ("npm", "--prefix", "frontend", "run", "build")),
    Command("packaged serving bundle", ("uv", "run", "poe", "wp3-1-docker-acceptance")),
)

PLANS: Mapping[Tier, TierPlan] = {
    Tier.PR: TierPlan(
        tier=Tier.PR,
        purpose="Code health",
        commands=PR_COMMANDS,
        required_environment=("TOUCHLINE_DB_URL",),
    ),
    Tier.MILESTONE: TierPlan(
        tier=Tier.MILESTONE,
        purpose="Scientific and contract integrity",
        commands=MILESTONE_COMMANDS,
        required_environment=("TOUCHLINE_DB_URL", "TOUCHLINE_FULL_COHORT_DB_URL"),
        requires_clean_tree=True,
        unavailable_reason=(
            "the retained 15-sentinel mutation runner has not been selected and registered; "
            "WP5.4 must not substitute the historical 350-case harness or treat its absence "
            "as a pass"
        ),
    ),
    Tier.RELEASE: TierPlan(
        tier=Tier.RELEASE,
        purpose="Reproducibility and deployability",
        commands=MILESTONE_COMMANDS,
        required_environment=("TOUCHLINE_DB_URL", "TOUCHLINE_FULL_COHORT_DB_URL"),
        requires_clean_tree=True,
        unavailable_reason=(
            "the current-candidate broader mutation sweep has not been defined; release validation "
            "cannot pass before that fail-closed control and its deployment/recovery inputs exist"
        ),
    ),
}

# libpq accepts connection keywords in a PostgreSQL URI's query string.  These can supersede or
# supplement the authority host after it has been checked, so this orchestration boundary rejects
# every query parameter that can select a connection destination or load one from a service file.
LIBPQ_ROUTING_PARAMETERS = frozenset({"host", "hostaddr", "port", "service"})
LIBPQ_ROUTING_ENVIRONMENT = frozenset(
    {"PGHOST", "PGHOSTADDR", "PGPORT", "PGSERVICE", "PGSERVICEFILE"}
)

# Pull-request validation is fixture-only.  These opt-ins expand pytest collection to data-backed
# acceptance tests and must never leak from a developer's shell into PR child commands.
PR_DATA_SCOPE_ENVIRONMENT = frozenset({"TOUCHLINE_FULL_COHORT_DB_URL", "TOUCHLINE_FULL_SOURCE"})
FULL_COHORT_DATABASE_ENVIRONMENT = "TOUCHLINE_FULL_COHORT_DB_URL"
FULL_SOURCE_ENVIRONMENT = "TOUCHLINE_FULL_SOURCE"

# Keep this as a named command so its database scope is granted by command intent, not by the
# enclosing tier.  Milestone and release plans both contain PR commands before this one.
FULL_COHORT_COMMAND = MILESTONE_COMMANDS[len(PR_COMMANDS)]


def is_local_postgres_url(value: str) -> bool:
    """Return whether *value* names a loopback PostgreSQL target.

    Validation invokes fixture integration tests, which may write isolated schemas.  Requiring a
    loopback target prevents this orchestration layer from ever writing to a deployed database.
    Unknown URL forms fail closed.
    """
    try:
        parsed = urlsplit(value)
        query_parameters = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return False
    authority_hosts = unquote(parsed.netloc.rsplit("@", 1)[-1])
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or not parsed.hostname
        or "," in authority_hosts
    ):
        return False
    if any(key.lower() in LIBPQ_ROUTING_PARAMETERS for key, _ in query_parameters):
        return False
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def plan_for(tier: Tier) -> TierPlan:
    """Return the immutable command plan for *tier*."""
    return PLANS[tier]


def require_prerequisites(
    plan: TierPlan,
    environment: Mapping[str, str],
    *,
    is_clean_tree: Callable[[], bool],
) -> None:
    """Check every tier prerequisite before dispatching any command."""
    for variable in plan.required_environment:
        value = environment.get(variable)
        if not value:
            raise ValidationPrerequisiteError(f"{plan.tier}: {variable} is required")
        if not is_local_postgres_url(value):
            raise ValidationPrerequisiteError(
                f"{plan.tier}: {variable} must name a loopback PostgreSQL database; refusing "
                "a possible deployed write target"
            )
    if plan.requires_clean_tree and not is_clean_tree():
        raise ValidationPrerequisiteError(f"{plan.tier}: a clean Git working tree is required")
    if plan.unavailable_reason:
        raise TierUnavailableError(f"{plan.tier}: unavailable because {plan.unavailable_reason}")


def git_tree_is_clean(repo_root: Path) -> bool:
    """Use Git's porcelain status without modifying the worktree."""
    result = subprocess.run(
        ("git", "status", "--porcelain"),
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and not result.stdout.strip()


def child_environment_for(command: Command, environment: Mapping[str, str]) -> dict[str, str]:
    """Scope child variables to the command that is allowed to consume them.

    PR/code-health commands can appear inside a broader tier, so their data-scope exclusions are
    command-based rather than tier-based.  Only the explicit full-cohort command receives its
    populated-cohort database URL.  Full-source opt-in remains outside every tier here.
    """
    removed_environment = LIBPQ_ROUTING_ENVIRONMENT | {FULL_SOURCE_ENVIRONMENT}
    if command != FULL_COHORT_COMMAND:
        removed_environment = removed_environment | {FULL_COHORT_DATABASE_ENVIRONMENT}
    return {
        variable: value
        for variable, value in environment.items()
        if variable.upper() not in removed_environment
    }


def run_tier(
    tier: Tier,
    environment: Mapping[str, str],
    *,
    repo_root: Path,
    run_command: Callable[[Sequence[str], Path, Mapping[str, str]], int] | None = None,
    is_clean_tree: Callable[[], bool] | None = None,
) -> int:
    """Validate preconditions then run existing commands in their documented order."""
    plan = plan_for(tier)
    require_prerequisites(
        plan,
        environment,
        is_clean_tree=is_clean_tree or (lambda: git_tree_is_clean(repo_root)),
    )
    dispatch = run_command or _run_command
    for command in plan.commands:
        print(f"==> {command.label}: {' '.join(command.argv)}")
        result = dispatch(command.argv, repo_root, child_environment_for(command, environment))
        if result != 0:
            return result
    return 0


def _run_command(argv: Sequence[str], repo_root: Path, environment: Mapping[str, str]) -> int:
    return subprocess.run(tuple(argv), cwd=repo_root, env=dict(environment), check=False).returncode


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a WP5.4 validation tier.")
    parser.add_argument("tier", choices=tuple(tier.value for tier in Tier))
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the plan without checks or commands."
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for ``uv run poe validation-<tier>``."""
    args = _parse_args(argv)
    plan = plan_for(Tier(args.tier))
    if args.dry_run:
        print(f"{plan.tier}: {plan.purpose}")
        for command in plan.commands:
            print(f"{command.label}: {' '.join(command.argv)}")
        if plan.unavailable_reason:
            print(f"BLOCKED: {plan.unavailable_reason}")
        return 0

    repo_root = Path(__file__).resolve().parents[3]
    try:
        return run_tier(Tier(args.tier), os.environ, repo_root=repo_root)
    except ValidationPrerequisiteError as error:
        print(f"Validation refused: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - exercised through the console entry point.
    raise SystemExit(main())
