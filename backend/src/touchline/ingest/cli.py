"""Command-line entry point for the WP0.3 ingestion.

    uv run poe ingest            # load, refusing to touch a non-empty database
    uv run poe ingest --reset    # destructive reset, then load

The loader is not idempotent. `--reset` is the supported way to re-run.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

import psycopg

from touchline.config import get_settings
from touchline.ingest import load as loader
from touchline.ingest.parse import parse_competitions, parse_matches, parse_shots
from touchline.ingest.records import Competition, Match, Player, Shot, Team
from touchline.ingest.source import WORLD_CUP_2022, StatsBombSource


@dataclass(frozen=True, slots=True)
class SourceCounts:
    """What the source files said, counted before anything was written."""

    matches: int
    shots: int
    shots_without_location: int
    shots_without_player: int


def collect(
    source: StatsBombSource, competition_id: int, season_id: int
) -> tuple[list[Competition], list[Team], list[Player], list[Match], list[Shot], SourceCounts]:
    """Read and parse the whole scope into memory.

    A World Cup is small enough that streaming would add complexity for no benefit; if that stops
    being true the reconciliation report is what will say so.
    """
    all_competitions = parse_competitions(source.competitions())
    competitions = [
        c
        for c in all_competitions
        if c.competition_id == competition_id and c.season_id == season_id
    ]
    if not competitions:
        raise SystemExit(f"competition {competition_id}/{season_id} is not in competitions.json")

    matches, teams = parse_matches(source.matches(competition_id, season_id))
    match_ids = [m.match_id for m in matches]

    print(f"  fetching events for {len(match_ids)} matches ...", flush=True)
    source.prefetch_events(match_ids)

    shots: list[Shot] = []
    players: dict[int, Player] = {}
    for match_id in match_ids:
        match_shots, match_players = parse_shots(match_id, source.events(match_id))
        shots.extend(match_shots)
        for player in match_players:
            players[player.player_id] = player

    counts = SourceCounts(
        matches=len(matches),
        shots=len(shots),
        shots_without_location=sum(1 for s in shots if s.location_x is None),
        shots_without_player=sum(1 for s in shots if s.player_id is None),
    )
    return (
        competitions,
        teams,
        sorted(players.values(), key=lambda p: p.player_id),
        matches,
        shots,
        counts,
    )


def _reconcile(source_counts: SourceCounts, db: loader.LoadCounts) -> bool:
    """Compare what the source said with what the database holds.

    Printed every run. A load that inserted the wrong number of rows without anyone noticing is
    the failure mode this exists to prevent.
    """
    checks = [
        ("matches", source_counts.matches, db.matches),
        ("shots", source_counts.shots, db.shots),
    ]
    print("\nReconciliation (source -> database)")
    ok = True
    for name, expected, actual in checks:
        mark = "OK " if expected == actual else "MISMATCH"
        if expected != actual:
            ok = False
        print(f"  [{mark}] {name}: source {expected}, database {actual}")

    print("\nCoverage notes")
    print(f"  shots with no location: {source_counts.shots_without_location}")
    print(f"  shots with no attributed player: {source_counts.shots_without_player}")
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load a StatsBomb competition-season slice.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="drop and recreate the tables first (destructive; the supported way to re-run)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="fail rather than download; use only what is already cached",
    )
    parser.add_argument("--competition-id", type=int, default=WORLD_CUP_2022[0])
    parser.add_argument("--season-id", type=int, default=WORLD_CUP_2022[1])
    args = parser.parse_args(argv)

    settings = get_settings()
    source = StatsBombSource(offline=args.offline)

    print(f"Scope: competition {args.competition_id}, season {args.season_id}")
    competitions, teams, players, matches, shots, source_counts = collect(
        source, args.competition_id, args.season_id
    )
    print(
        f"  parsed {len(matches)} matches, {len(teams)} teams, "
        f"{len(players)} players, {len(shots)} shots"
    )

    with psycopg.connect(settings.db_url_str) as conn:
        if args.reset:
            print("  resetting schema (destructive) ...")
            loader.reset_schema(conn)
        try:
            loader.load_all(
                conn,
                competitions=competitions,
                teams=teams,
                players=players,
                matches=matches,
                shots=shots,
            )
        except loader.NotIdempotentError as exc:
            print(f"\nRefused to load: {exc}", file=sys.stderr)
            return 1

        db_counts = loader.count_rows(conn)

    print(
        f"\nLoaded: {db_counts.competitions} competitions, {db_counts.teams} teams, "
        f"{db_counts.players} players, {db_counts.matches} matches, {db_counts.shots} shots"
    )
    reconciled = _reconcile(source_counts, db_counts)
    if not reconciled:
        print("\nReconciliation FAILED - database does not match the source.", file=sys.stderr)
        return 1
    print("\nReconciliation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
