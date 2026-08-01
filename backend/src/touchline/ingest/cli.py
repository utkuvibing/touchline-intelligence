"""Command-line entry point for the WP0.3 ingestion.

    uv run poe ingest            # load, refusing to touch a non-empty database
    uv run poe ingest --reset    # destructive reset, then load

The loader is not idempotent. `--reset` is the supported way to re-run.

This module owns the transaction. The flow is deliberately:

    reset (optional) -> load rows -> read counts back -> reconcile -> commit

Reconciliation happens *inside* the transaction, against rows that are written but not yet durable.
A mismatch therefore rolls the whole thing back, so the database never holds a load that failed its
own check. Committing first and reporting afterwards would turn reconciliation into a description
of data already kept.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

import psycopg

from touchline.config import get_settings
from touchline.ingest import load as loader
from touchline.ingest.parse import parse_competitions, parse_events, parse_lineups, parse_matches
from touchline.ingest.records import (
    Competition,
    Event,
    EventRelation,
    Lineup,
    LineupCard,
    LineupMembership,
    LineupPosition,
    Match,
    Player,
    Possession,
    Shot,
    ShotFreezeFramePlayer,
    Team,
)
from touchline.ingest.source import WORLD_CUP_2022, StatsBombSource


class ReconciliationError(RuntimeError):
    """Loaded counts do not match the source.

    Raised inside the connection context so the transaction is rolled back rather than kept.
    """


@dataclass(frozen=True, slots=True)
class SourceCounts:
    """What the source files said, counted before anything was written."""

    competitions: int = 0
    seasons: int = 0
    competition_seasons: int = 0
    teams: int = 0
    players: int = 0
    matches: int = 0
    match_teams: int = 0
    lineups: int = 0
    lineup_memberships: int = 0
    lineup_positions: int = 0
    lineup_cards: int = 0
    possessions: int = 0
    events: int = 0
    event_relations: int = 0
    shots: int = 0
    shot_freeze_frame_players: int = 0
    shots_without_location: int = 0
    shots_without_player: int = 0


@dataclass(frozen=True, slots=True)
class CollectedScope:
    """Every parsed entity set required by the normalized loader."""

    competitions: list[Competition]
    teams: list[Team]
    players: list[Player]
    matches: list[Match]
    shots: list[Shot]
    source_counts: SourceCounts
    lineups: list[Lineup]
    memberships: list[LineupMembership]
    positions: list[LineupPosition]
    cards: list[LineupCard]
    possessions: list[Possession]
    events: list[Event]
    relations: list[EventRelation]
    freeze_frames: list[ShotFreezeFramePlayer]


def collect(source: StatsBombSource, competition_id: int, season_id: int) -> CollectedScope:
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
    source.prefetch_match_files(match_ids)

    shots: list[Shot] = []
    lineups: list[Lineup] = []
    memberships: list[LineupMembership] = []
    positions: list[LineupPosition] = []
    cards: list[LineupCard] = []
    possessions: list[Possession] = []
    events: list[Event] = []
    relations: list[EventRelation] = []
    freeze_frames: list[ShotFreezeFramePlayer] = []
    players: dict[int, Player] = {}
    for match_id in match_ids:
        match_lineups, match_memberships, match_positions, match_cards, lineup_players = (
            parse_lineups(match_id, source.lineups(match_id))
        )
        (
            match_events,
            match_relations,
            match_shots,
            match_frames,
            match_possessions,
            event_players,
        ) = parse_events(match_id, source.events(match_id))
        shots.extend(match_shots)
        lineups.extend(match_lineups)
        memberships.extend(match_memberships)
        positions.extend(match_positions)
        cards.extend(match_cards)
        possessions.extend(match_possessions)
        events.extend(match_events)
        relations.extend(match_relations)
        freeze_frames.extend(match_frames)
        for player in [*lineup_players, *event_players]:
            players[player.player_id] = player

    counts = SourceCounts(
        competitions=len(competitions),
        seasons=len({c.season_id for c in competitions}),
        competition_seasons=len(competitions),
        teams=len(teams),
        players=len(players),
        matches=len(matches),
        match_teams=len(matches) * 2,
        lineups=len(lineups),
        lineup_memberships=len(memberships),
        lineup_positions=len(positions),
        lineup_cards=len(cards),
        possessions=len(possessions),
        events=len(events),
        event_relations=len(relations),
        shots=len(shots),
        shot_freeze_frame_players=len(freeze_frames),
        shots_without_location=sum(1 for s in shots if s.location_x is None),
        shots_without_player=sum(1 for s in shots if s.player_id is None),
    )
    return CollectedScope(
        competitions=competitions,
        teams=teams,
        players=sorted(players.values(), key=lambda p: p.player_id),
        matches=matches,
        shots=shots,
        source_counts=counts,
        lineups=lineups,
        memberships=memberships,
        positions=positions,
        cards=cards,
        possessions=possessions,
        events=events,
        relations=relations,
        freeze_frames=freeze_frames,
    )


def reconcile(source_counts: SourceCounts, db: loader.LoadCounts) -> bool:
    """Compare what the source said with what the database holds, and print the comparison.

    Read inside the loading transaction, so `db` reflects uncommitted rows. That is the point: a
    mismatch must be able to prevent the commit, not merely describe it.
    """
    checks = [
        (name, getattr(source_counts, name), getattr(db, name))
        for name in loader.LoadCounts.__dataclass_fields__
    ]
    print("\nReconciliation (source -> database, before commit)")
    ok = True
    for name, expected, actual in checks:
        if expected != actual:
            ok = False
        print(
            f"  [{'OK ' if expected == actual else 'MISMATCH'}] "
            f"{name}: source {expected}, database {actual}"
        )

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
    collected = collect(source, args.competition_id, args.season_id)
    print(
        f"  parsed {len(collected.matches)} matches, {len(collected.teams)} teams, "
        f"{len(collected.players)} players, {len(collected.shots)} shots"
    )

    try:
        # psycopg commits on a clean exit from this block and rolls back on any exception, so
        # raising below is how a failed reconciliation discards the load.
        with psycopg.connect(settings.db_url_str) as conn:
            if args.reset:
                print("  resetting schema (destructive) ...")
                loader.reset_schema(conn)

            loader.load_all(
                conn,
                competitions=collected.competitions,
                teams=collected.teams,
                players=collected.players,
                matches=collected.matches,
                shots=collected.shots,
                lineups=collected.lineups,
                memberships=collected.memberships,
                positions=collected.positions,
                cards=collected.cards,
                possessions=collected.possessions,
                events=collected.events,
                relations=collected.relations,
                freeze_frames=collected.freeze_frames,
            )

            db_counts = loader.count_rows(conn)
            print(
                f"\nWritten (uncommitted): {db_counts.competitions} competitions, "
                f"{db_counts.teams} teams, {db_counts.players} players, "
                f"{db_counts.matches} matches, {db_counts.shots} shots"
            )

            if not reconcile(collected.source_counts, db_counts):
                raise ReconciliationError("loaded counts do not match the source")
    except loader.NotIdempotentError as exc:
        print(f"\nRefused to load: {exc}", file=sys.stderr)
        return 1
    except ReconciliationError as exc:
        print(f"\nRolled back: {exc}. Nothing was committed.", file=sys.stderr)
        return 1

    provenance_path = source.write_provenance(f"competition-{args.competition_id}-{args.season_id}")
    print(f"\nCommitted. Provenance written to {provenance_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
