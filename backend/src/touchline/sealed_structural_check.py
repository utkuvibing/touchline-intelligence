"""Target-free structural validation of the sealed external evaluation sets (M5 WP5.1).

This is the *only* access any sealed tournament permits before M7 opens its qualification run,
per ``touchline.sealed_scope``: file existence, schema compatibility, match identifiers,
coordinate bounds and parser success.

**What this module must never emit**, in its report or its logs: shot outcomes, goal counts,
conversion rates, model scores, or any row-level preview. Every returned fact below is
label-free by construction — the scan reads event locations and identity fields only, and the
report schema is pinned by unit tests that forbid outcome-bearing keys.

Coordinate bounds admit the one measured source exception already documented in DATA_SOURCE.md
(``location_x = 120.1``); anything outside ``[0, 120.1] x [0, 80]`` is counted as a violation.
Violation counts are reported without row previews.

Usage::

    python -m touchline.sealed_structural_check check   # full structural validation
    python -m touchline.sealed_structural_check survey  # label-free future-reservation scan
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from touchline.ingest.source import SOURCE_COMMIT, SOURCE_COMMIT_DATE, StatsBombSource
from touchline.sealed_scope import (
    PERMITTED_ACCESS,
    SEALED_SCOPES,
    SEALED_SET_NAMES,
)

#: Keys every match record must carry for the current parsers to accept the file.
MATCH_REQUIRED_KEYS = (
    "match_id",
    "match_date",
    "kick_off",
    "competition",
    "season",
    "home_team",
    "away_team",
)

#: Keys every event record must carry; ``location`` is optional and validated when present.
EVENT_REQUIRED_KEYS = (
    "id",
    "index",
    "period",
    "timestamp",
    "type",
    "possession",
    "possession_team",
    "team",
)

LINEUP_PLAYER_KEYS = ("player_id", "player_name")

MAX_LOCATION_X = 120.1
MAX_LOCATION_Y = 80.0

REPORT_PATH = Path("reports/wp5.1-sealed-structural-validation.md")


@dataclass(frozen=True)
class MatchFileCheck:
    """Label-free facts about one sealed tournament's match file."""

    relative_path: str
    sha256: str
    byte_count: int
    match_count: int
    unique_match_ids: int
    missing_keys_by_record: int
    scope_mismatches: int
    parse_success: bool


@dataclass(frozen=True)
class EventScan:
    """Aggregated parser-success and coordinate-bounds facts across one tournament."""

    matches_scanned: int
    event_files_parsed: int
    lineup_files_parsed: int
    schema_failures: int
    locations_scanned: int
    coordinate_violations: int
    min_x: float | None
    max_x: float | None
    min_y: float | None
    max_y: float | None


@dataclass(frozen=True)
class ScopeResult:
    """Everything the structural validation may say about one sealed tournament."""

    name: str
    scope: tuple[int, int]
    match_file: MatchFileCheck
    events: EventScan


@dataclass
class _MutableScan:
    """Accumulator for :class:`EventScan`; never leaves this module."""

    matches_scanned: int = 0
    event_files_parsed: int = 0
    lineup_files_parsed: int = 0
    schema_failures: int = 0
    locations_scanned: int = 0
    coordinate_violations: int = 0
    xs: list[float] = field(default_factory=list)
    ys: list[float] = field(default_factory=list)


def validate_match_payload(
    payload: Any, relative_path: str, sha256: str, raw_bytes: int, scope: tuple[int, int]
) -> MatchFileCheck:
    """Check one sealed tournament's match file against the current parser's expectations."""
    if not isinstance(payload, list):
        return MatchFileCheck(relative_path, sha256, raw_bytes, 0, 0, 0, 0, False)
    missing_keys = 0
    mismatches = 0
    ids: set[int] = set()
    for entry in payload:
        if not isinstance(entry, dict):
            missing_keys += 1
            continue
        missing_keys += sum(1 for key in MATCH_REQUIRED_KEYS if key not in entry)
        try:
            match_id = int(entry["match_id"])
        except (KeyError, TypeError, ValueError):
            continue
        ids.add(match_id)
        competition = entry.get("competition")
        season = entry.get("season")
        if (
            not isinstance(competition, dict)
            or not isinstance(season, dict)
            or competition.get("competition_id") != scope[0]
            or season.get("season_id") != scope[1]
        ):
            mismatches += 1
    return MatchFileCheck(
        relative_path=relative_path,
        sha256=sha256,
        byte_count=raw_bytes,
        match_count=len(payload),
        unique_match_ids=len(ids),
        missing_keys_by_record=missing_keys,
        scope_mismatches=mismatches,
        parse_success=bool(payload) and len(ids) == len(payload) and mismatches == 0,
    )


def scan_event_payload(payload: Any, scan: _MutableScan) -> None:
    """Fold one parsed events file into the aggregate scan; outcomes are never read."""
    scan.event_files_parsed += 1
    if not isinstance(payload, list):
        scan.schema_failures += 1
        return
    for event in payload:
        if not isinstance(event, dict) or any(key not in event for key in EVENT_REQUIRED_KEYS):
            scan.schema_failures += 1
            continue
        location = event.get("location")
        if not isinstance(location, list) or len(location) != 2:
            continue
        x_value, y_value = location
        if not isinstance(x_value, (int, float)) or not isinstance(y_value, (int, float)):
            scan.coordinate_violations += 1
            continue
        x_float, y_float = float(x_value), float(y_value)
        if x_float < 0.0 or x_float > MAX_LOCATION_X or y_float < 0.0 or y_float > MAX_LOCATION_Y:
            scan.coordinate_violations += 1
        scan.locations_scanned += 1
        scan.xs.append(x_float)
        scan.ys.append(y_float)


def scan_lineup_payload(payload: Any, scan: _MutableScan) -> None:
    """Confirm a lineups file parses into team entries with player records; nothing more."""
    scan.lineup_files_parsed += 1
    if not isinstance(payload, list):
        scan.schema_failures += 1
        return
    for entry in payload:
        lineup = entry.get("lineup") if isinstance(entry, dict) else None
        if not isinstance(lineup, list) or any(
            not isinstance(player, dict) or any(key not in player for key in LINEUP_PLAYER_KEYS)
            for player in lineup
        ):
            scan.schema_failures += 1


def _scan_tournament_events(
    source: StatsBombSource, match_ids: list[int], workers: int = 8
) -> _MutableScan:
    """Parse each match's events and lineups from the warmed cache, folding into one scan."""
    scan = _MutableScan()
    source.prefetch_match_files(match_ids, workers=workers)
    for match_id in match_ids:
        scan.matches_scanned += 1
        scan_event_payload(source.events(match_id), scan)
        scan_lineup_payload(source.lineups(match_id), scan)
    return scan


def check_scope(source: StatsBombSource, scope: tuple[int, int]) -> ScopeResult:
    """Run the full target-free structural validation for one sealed tournament."""
    relative_path = f"matches/{scope[0]}/{scope[1]}.json"
    payload = source.matches(scope[0], scope[1])
    cached = source.cache_dir / relative_path
    raw_bytes = cached.stat().st_size
    sha256 = source.provenance()["files_sha256"][relative_path]
    match_file = validate_match_payload(payload, relative_path, sha256, raw_bytes, scope)
    match_ids = sorted(
        entry["match_id"]
        for entry in payload
        if isinstance(entry, dict) and isinstance(entry.get("match_id"), int)
    )
    scan = _scan_tournament_events(source, match_ids)
    return ScopeResult(
        name=SEALED_SET_NAMES[scope],
        scope=scope,
        match_file=match_file,
        events=EventScan(
            matches_scanned=scan.matches_scanned,
            event_files_parsed=scan.event_files_parsed,
            lineup_files_parsed=scan.lineup_files_parsed,
            schema_failures=scan.schema_failures,
            locations_scanned=scan.locations_scanned,
            coordinate_violations=scan.coordinate_violations,
            min_x=min(scan.xs) if scan.xs else None,
            max_x=max(scan.xs) if scan.xs else None,
            min_y=min(scan.ys) if scan.ys else None,
            max_y=max(scan.ys) if scan.ys else None,
        ),
    )


def run_check(cache_dir: Path | None = None) -> tuple[list[ScopeResult], Path]:
    """Validate both sealed tournaments; write the provenance record and return the results."""
    source = StatsBombSource(cache_dir)
    results = [check_scope(source, scope) for scope in sorted(SEALED_SCOPES)]
    provenance_path = source.write_provenance("wp5.1-sealed-sets")
    return results, provenance_path


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def overall_verdict(results: Iterable[ScopeResult]) -> bool:
    """The single PASS/FAIL rule for the structural validation.

    Any of the following fails a tournament and with it the overall verdict: a match-file parse
    failure, any event/lineup schema failure, or **any coordinate-bound violation**. Both the
    rendered report's overall line and the CLI exit status are derived from this one function,
    so they can never disagree.
    """
    return all(
        result.match_file.parse_success
        and result.events.schema_failures == 0
        and result.events.coordinate_violations == 0
        for result in results
    )


def render_report(results: Iterable[ScopeResult], generated_utc: str) -> str:
    """Render the committed report. Outcome-bearing facts are structurally absent."""
    lines = [
        "# WP5.1 — Sealed-set target-free structural validation",
        "",
        "**Access class:** target-free structural validation only "
        f"(`{PERMITTED_ACCESS}`). This report contains no shot outcomes, goal counts, conversion "
        "rates, model scores or row-level previews, and may never gain any.",
        "",
        f"- Source commit: `{SOURCE_COMMIT}` ({SOURCE_COMMIT_DATE})",
        f"- Generated (UTC): {generated_utc}",
        "- Registry: `data/model/v2_evaluation_registry.json`",
        "- Provenance: `data/provenance/wp5.1-sealed-sets.json`",
        "",
        "| Tournament | Scope | Match file | SHA-256 (first 12) | Matches | Unique IDs | "
        "Scope mismatches | Missing keys | Parse |",
        "|---|---|---|---|---:|---:|---:|---:|---|",
    ]
    for result in results:
        mf = result.match_file
        parse_ok = mf.parse_success and result.events.schema_failures == 0
        verdict = "pass" if parse_ok else "FAIL"
        lines.append(
            f"| {result.name} | {result.scope[0]}/{result.scope[1]} | `{mf.relative_path}` | "
            f"`{mf.sha256[:12]}` | {mf.match_count} | {mf.unique_match_ids} | "
            f"{mf.scope_mismatches} | {mf.missing_keys_by_record} | {verdict} |"
        )
    lines.extend(
        [
            "",
            "## Parser success and coordinate bounds (event-embedded locations)",
            "",
            "| Tournament | Matches scanned | Event files | Lineup files | Schema failures | "
            "Locations scanned | Violations | X range | Y range |",
            "|---|---:|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for result in results:
        ev = result.events
        lines.append(
            f"| {result.name} | {ev.matches_scanned} | {ev.event_files_parsed} | "
            f"{ev.lineup_files_parsed} | {ev.schema_failures} | {ev.locations_scanned} | "
            f"{ev.coordinate_violations} | [{_fmt(ev.min_x)}, {_fmt(ev.max_x)}] | "
            f"[{_fmt(ev.min_y)}, {_fmt(ev.max_y)}] |"
        )
    lines.extend(
        [
            "",
            "Admitted bounds are `[0, 120.1] x [0, 80]`; the upper X bound carries the measured "
            "source exception `location_x = 120.1` documented in `DATA_SOURCE.md`. A non-zero "
            "violation or schema-failure count fails this report.",
            "",
            f"**Overall: {'PASS' if overall_verdict(results) else 'FAIL'}**",
            "",
        ]
    )
    return "\n".join(lines)


def survey_future_reservations(cache_dir: Path | None = None) -> None:
    """Print a label-free candidate table of complete men's tournaments after Euro 2024.

    Reads only ``competitions.json`` and match-file existence/count. No event file is read, so
    no outcome can surface. The reservation decision itself belongs to the human-recorded
    registry entry, not to this script.
    """
    source = StatsBombSource(cache_dir)
    competitions = source.competitions()
    euro_2024_end = dt.date(2024, 7, 14)
    seen: set[tuple[int, int]] = set()
    print(f"{'name':<45} {'scope':<12} {'season':<20} {'matches':>7} {'last_update':<22}")
    for entry in competitions:
        if entry.get("competition_gender") != "male":
            continue
        cid, sid = int(entry["competition_id"]), int(entry["season_id"])
        if (cid, sid) in seen or (cid, sid) in SEALED_SCOPES:
            continue
        seen.add((cid, sid))
        updated = entry.get("match_updated") or ""
        if updated[:10] < euro_2024_end.isoformat():
            continue
        try:
            payload = source.matches(cid, sid)
            count = len(payload)
        except Exception as exc:  # survey reports unavailability, never dies
            print(f"{entry['competition_name']:<45} {cid}/{sid:<8} {entry['season_name']:<20}")
            print(f"    unavailable: {exc}")
            continue
        print(
            f"{entry['competition_name']:<45} {cid}/{sid:<8} "
            f"{entry['season_name']!s:<20} {count:>7} {updated:<22}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check_parser = sub.add_parser("check", help="run the target-free structural validation")
    check_parser.add_argument("--cache-dir", type=Path, default=None)
    check_parser.add_argument("--report", type=Path, default=REPORT_PATH)
    survey_parser = sub.add_parser("survey", help="list post-Euro-2024 men's tournaments")
    survey_parser.add_argument("--cache-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.command == "survey":
        survey_future_reservations(args.cache_dir)
        return 0
    results, provenance_path = run_check(args.cache_dir)
    generated = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    report = render_report(results, generated)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report, encoding="utf-8", newline="\n")
    print(f"report written to {args.report}")
    print(f"provenance written to {provenance_path}")
    if not overall_verdict(results):
        print("structural validation FAILED", file=sys.stderr)
        return 1
    print("structural validation PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
