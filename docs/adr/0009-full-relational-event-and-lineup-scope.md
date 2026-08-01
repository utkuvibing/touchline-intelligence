# ADR 0009: Full relational event and lineup scope for WP1.2

## Status

Accepted — 2026-08-01; supersedes
[ADR 0008](0008-shot-focused-relational-boundary.md)

## Context

ADR 0008 implemented a useful five-table migration foundation but deferred lineups and generic
events. The author had explicitly approved the broader ADR 0002 direction for WP1.2, so that
deferral did not reflect the governing scope. Direct measurement of the pinned World Cup 2022
snapshot found 64 lineup files, 3,244 match-team-player memberships, and 234,637 events across 33
types, providing evidence for the wider model rather than requiring fields to be guessed.

## Decision

WP1.2 implements competition-season normalization, match-team participation, source lineups and
membership, position and card children, possessions, every generic event, directed related-event
links, typed Shot details, and embedded Shot freeze-frame actors. Shared event fields are typed
relational columns. Sparse and evolving non-Shot type-specific structures are retained in JSONB;
Shot structures are relational and provider xG is discarded before persistence.

The existing ordered migration runner and migrations 0001–0002 remain history. Migrations 0003–0005
upgrade that foundation without inventing fields absent from the legacy database. No secondary
indexes are added before WP1.5 supplies query-plan evidence.

## Consequences

Lineup membership is not called an appearance: 1,249 measured memberships have no position
interval. Related-event references remain directed because 107,528 measured links are not
reciprocal. Source position intervals are preserved without a `to >= from` constraint because 17
measured rows violate that assumption. Embedded Shot freeze frames remain event snapshots and are
never described as tracking data or StatsBomb 360.

WP1.3 still owns the four-tournament cohort, idempotent upserts, conflict policy, and run manifest.
This decision does not authorize those changes or automatic migration of the live Neon database.
