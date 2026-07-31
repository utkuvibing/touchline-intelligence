# ADR 0002: PostgreSQL as the primary database

## Status

Accepted

## Context

The product needs durable football entities, constraints, idempotent ingestion, analytical joins, API queries, and deliberate SQL learning. Raw StatsBomb JSON is valuable source material but does not by itself enforce relationships, prevent duplicates, or provide a stable analytical contract.

## Decision

Use PostgreSQL as the primary serving and analytical database for the project. Preserve raw source files or immutable source references and ingestion manifests for provenance. Model competitions, seasons, matches, teams, players, lineups, events, and relevant event details relationally, retaining JSONB only for source fields that are sparse, evolving, or not yet promoted to typed columns.

Database changes use ordered migrations. Natural/source identifiers and uniqueness constraints support idempotent upserts. Core analytical queries should be expressible and tested in SQL before convenience wrappers obscure them.

## Alternatives considered

- **Raw JSON only:** simplest ingestion, but weak constraints, joins, discoverability, and SQL learning value.
- **SQLite/DuckDB as primary:** useful for analysis and fixtures, but less representative of the intended API/deployment path and concurrent access. They may be temporary developer tools only after justification.
- **Cloud-managed backend database immediately:** deferred because local PostgreSQL supplies the required semantics without early vendor and deployment complexity.
- **Warehouse plus transformation framework:** rejected until scale or transformation lineage creates a demonstrated need.

## Consequences

- The project gains explicit relationships, constraints, migrations, indexes, and realistic SQL practice.
- Local setup requires Docker or a compatible PostgreSQL installation.
- The schema must balance queryability with the long tail of event attributes.
- Raw data provenance remains necessary; the database is not treated as the only copy of source truth.
- Query performance should be measured before indexes or denormalized tables are added.

## Review trigger

Review if measured analytical workloads are impractical in PostgreSQL, deployment constraints make it unavailable, or a well-defined module needs another store. A second database requires its own ADR and may not replace raw-data provenance.

