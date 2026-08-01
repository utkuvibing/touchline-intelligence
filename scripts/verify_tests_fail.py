"""Verify that the test suite actually protects what it claims to.

A green suite proves the tests pass, not that they would fail if the behaviour broke. This script
introduces one deliberate break per protected contract, runs the relevant tests, asserts they fail,
and restores the file.

Run with a clean working tree:

    uv run python scripts/verify_tests_fail.py

It has already earned its place twice. It found that the /health liveness test passed even when
/health was made to call the database (the failure was invisible from the response body), and that
the /ready secret-leak test passed for the wrong reason, because it used a blocklist of substrings
that the actual driver error did not happen to contain. Both tests were rewritten.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

HEALTH_ANCHOR = "    settings = get_settings()\n    return Health("
HEALTH_BROKEN = (
    "    settings = get_settings()\n"
    "    _check_database(settings)  # DELIBERATE BREAK\n"
    "    return Health("
)

DB_URL_ANCHOR = "    db_url: PostgresDsn = Field(\n        description="
DB_URL_BROKEN = (
    "    db_url: PostgresDsn = Field(\n"
    '        default="postgresql://a:b@localhost:5432/c",  # DELIBERATE BREAK\n'
    "        description="
)

OPS_TESTS = "uv run pytest backend/tests/test_ops_endpoints.py -q"
CONFIG_TESTS = "uv run pytest backend/tests/test_config.py -q"
PARSE_TESTS = "uv run pytest backend/tests/test_ingest_parse.py -q"
# These two only prove anything when TOUCHLINE_DB_URL is set - the loader tests need a live
# database, and the hermeticity break is invisible unless a TOUCHLINE_* variable is exported. The
# script reports MISSED otherwise, which is honest: an unrun test protects nothing.
LOAD_TESTS = "uv run pytest backend/tests/test_ingest_load_integration.py -q"
BASELINE_TESTS = "uv run pytest backend/tests/test_baseline_integration.py -q"
SHOTS_TESTS = "uv run pytest backend/tests/test_shots_integration.py -q"
FRONTEND_TESTS = "npm test"


@dataclass(frozen=True)
class Break:
    """One deliberate defect and the command that must notice it."""

    contract: str
    path: Path
    anchor: str
    replacement: str
    command: str
    cwd: Path


BREAKS: list[Break] = [
    Break(
        contract="/health must not touch the database (liveness)",
        path=ROOT / "backend/src/touchline/main.py",
        anchor=HEALTH_ANCHOR,
        replacement=HEALTH_BROKEN,
        command=OPS_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="db_url must have no default (fail fast on misconfiguration)",
        path=ROOT / "backend/src/touchline/config.py",
        anchor=DB_URL_ANCHOR,
        replacement=DB_URL_BROKEN,
        command=CONFIG_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="/ready must report an exception class name only (no secret leak)",
        path=ROOT / "backend/src/touchline/main.py",
        anchor="        return False, type(exc).__name__",
        replacement="        return False, str(exc)  # DELIBERATE BREAK",
        command=OPS_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="the 'no evaluated model' notice must stay while M0 has no model",
        path=FRONTEND / "components/HomeView.tsx",
        anchor='        <p role="note">{PROVISIONAL_NOTICE}</p>',
        replacement="        {/* DELIBERATE BREAK */}",
        command=FRONTEND_TESTS,
        cwd=FRONTEND,
    ),
    Break(
        contract="StatsBomb attribution must stay (licence obligation)",
        path=FRONTEND / "components/HomeView.tsx",
        anchor="          Data provided by StatsBomb.",
        replacement="          DELIBERATE BREAK.",
        command=FRONTEND_TESTS,
        cwd=FRONTEND,
    ),
    Break(
        contract="an absent shot location must stay NULL, never be coerced to a real coordinate",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor="    if raw is None:\n        return None, None",
        replacement="    if raw is None:\n        return 0.0, 0.0  # DELIBERATE BREAK",
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="a malformed location must raise, not be silently treated as absent",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor='        raise ParseError(f"expected location to be exactly [x, y], got {raw!r}")',
        replacement="        return None, None  # DELIBERATE BREAK",
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="a location must have exactly two elements, not merely at least two",
        path=ROOT / "backend/src/touchline/ingest/parse.py",
        anchor="    if not isinstance(raw, list) or len(raw) != 2:",
        replacement="    if not isinstance(raw, list) or len(raw) < 2:  # DELIBERATE BREAK",
        command=PARSE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="config tests must be hermetic against the real environment",
        path=ROOT / "backend/tests/test_config.py",
        anchor="        monkeypatch.delenv(name, raising=False)",
        replacement="        pass  # DELIBERATE BREAK",
        command=CONFIG_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="the loader must not commit - the caller owns the transaction",
        path=ROOT / "backend/src/touchline/ingest/load.py",
        anchor="        ),\n    )\n    return counts",
        replacement="        ),\n    )\n    conn.commit()  # DELIBERATE BREAK\n    return counts",
        command=LOAD_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="the base rate must exclude penalties",
        path=ROOT / "backend/src/touchline/baseline.py",
        anchor="    \"AND shot_type <> 'Penalty' \"",
        replacement='    "AND true "  # DELIBERATE BREAK',
        command=BASELINE_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="fetch_shots must make its own transaction read-only",
        path=ROOT / "backend/src/touchline/shots.py",
        anchor='cur.execute("SET TRANSACTION READ ONLY")',
        replacement="pass  # DELIBERATE BREAK",
        command=SHOTS_TESTS,
        cwd=ROOT,
    ),
    Break(
        contract="a map showing fewer shots than the API reports must disclose the shortfall",
        path=FRONTEND / "components/HomeView.tsx",
        anchor="            {missing > 0 && (",
        replacement="            {false && (  /* DELIBERATE BREAK */",
        command=FRONTEND_TESTS,
        cwd=FRONTEND,
    ),
    Break(
        contract="an empty database must raise, not report a conversion rate of zero",
        path=ROOT / "backend/src/touchline/baseline.py",
        anchor="    if shots == 0:\n        raise NoDataError(",
        replacement="    if False:  # DELIBERATE BREAK\n        raise NoDataError(",
        command=BASELINE_TESTS,
        cwd=ROOT,
    ),
]


def _tests_fail(command: str, cwd: Path) -> bool:
    """Run a test command and report whether it failed, which is the desired outcome here."""
    # shell=True is safe here: every command is a fixed literal defined above in this file,
    # with no interpolation of external input.
    result = subprocess.run(
        command,
        cwd=cwd,
        shell=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode != 0


def check(defect: Break) -> bool:
    """Apply one break, run its tests, restore the file. True when the break was caught."""
    original = defect.path.read_text(encoding="utf-8")
    if defect.anchor not in original:
        print(f"[SKIP  ] anchor no longer present: {defect.contract}")
        return False

    defect.path.write_text(original.replace(defect.anchor, defect.replacement, 1), encoding="utf-8")
    try:
        caught = _tests_fail(defect.command, defect.cwd)
    finally:
        defect.path.write_text(original, encoding="utf-8")

    print(f"[{'CAUGHT' if caught else 'MISSED'}] {defect.contract}")
    return caught


def main() -> int:
    results = [check(defect) for defect in BREAKS]
    if all(results):
        print(f"\nAll {len(results)} contracts are genuinely protected. Files restored.")
        return 0
    print(f"\n{results.count(False)} of {len(results)} breaks went unnoticed. Files restored.")
    print("A test that does not fail here is not protecting anything.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
