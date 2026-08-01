# ADR 0008: Shot-focused relational boundary for WP1.2

## Status

Accepted — 2026-08-01

## Context

ADR 0002 records a long-term relational direction that includes lineups, generic events, and typed
event details. The active plan narrows the next product path to a four-tournament shot cohort and a
shot-quality model, while the current source inventory and parser deliberately cover only matches
and Shot events. Designing unobserved lineup and heterogeneous-event fields now would be speculative
and would enlarge WP1.2 without a current consumer.

## Decision

WP1.2 makes the existing five-table shot model (`competitions`, `teams`, `players`, `matches`, and
`shots`) the constrained relational foundation. It uses consecutively numbered, hand-written SQL
migrations and a small checksum ledger implemented with psycopg; no ORM or migration dependency is
added. Source identifiers remain natural primary keys, display names remain non-unique labels, and
only invariants supported by the source contract are database checks.

ADR 0002's broader direction is not deleted, but lineups, appearances, generic events, and typed
non-shot details require a new observed consumer and source-field inventory before entering the
schema. Secondary indexes remain deferred until WP1.5 supplies measured query plans.

## Alternatives considered

- Model every entity named in ADR 0002 now: rejected because the active product path does not yet
  consume them and WP1.1 did not inventory their fields.
- Add a match-team bridge now: rejected because home/away relationships already serve current
  queries; a bridge is justified when lineup or participation data is actually ingested.
- Add Alembic or an ORM: rejected because two hand-written SQL migrations need ordering and drift
  detection, not an abstraction layer or another dependency.

## Consequences

The current API and fixture ingestion retain their five-table contract while gaining explicit
referential integrity and source-shape checks. Some cross-row football invariants remain pipeline
checks, stated explicitly in `docs/SCHEMA.md`. A later generic event or lineup consumer must revisit
the ERD rather than quietly extending `players` into a squad table.

## Review trigger

Review when a committed work package requires lineup/appearance denominators, non-shot event
analysis, related-event traversal, or database-level proof that an event team participated in its
match.
