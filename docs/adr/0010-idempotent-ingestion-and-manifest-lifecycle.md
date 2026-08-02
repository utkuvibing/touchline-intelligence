# ADR 0010: Idempotent ingestion and durable run lifecycle

## Status

Accepted — 2026-08-02

## Context

WP1.3 loads the fixed WC 2018, Euro 2020, WC 2022 and Euro 2024 cohort into a database that may
already contain WC 2022. Identical evidence must be a no-op, changed evidence must not be silently
rewritten, and a failed or interrupted process must leave an honest durable run record without
committing part of its source data.

## Decision

Each invocation has a durable ingestion run. A session-level PostgreSQL advisory lock serializes
source-data ownership. A second session-level lifecycle lock is held in shared mode by every active
invocation from before its `running` commit through its own terminal transition. A source-data lock
owner may classify older `running` runs as `interrupted` only while holding the lifecycle lock
exclusively; that exclusive ownership, not an elapsed-time guess, proves no active invocation owns
one of those rows. Lock order is lifecycle-shared then source-data; a source-data winner releases
shared lifecycle ownership before taking it exclusively for recovery, then downgrades continuously
to shared ownership before recording its own run. The invocation commits its own `running` record
separately, then performs every
source-derived merge, scoped reconciliation and `succeeded` transition in one data transaction.
An ordinary handled failure rolls that transaction back and records `failed` separately.

Neon operator commands use its direct PostgreSQL endpoint. The migration and ingestion command
boundaries reject a known `-pooler` hostname before opening a connection or creating any database
state. Railway's request-serving API keeps the pooled endpoint; the operator temporarily supplies
the direct URL through the same `TOUCHLINE_DB_URL` variable, so this decision adds no parallel
configuration value. The distinction is required because ingestion depends on session-level
advisory-lock ownership plus temporary-table and transaction state staying on the same session.

Bulk source rows enter temporary staging tables through PostgreSQL `COPY`. Identical source keys
are no-ops. A different source-derived fact under the same source commit and key raises
`SourceConflictError`, including differences in child rows and structural JSONB. Shared labels are
not identities: the fixed scope order selects a deterministic dimension label, while match-scoped
lineup labels retain their own variants. A changed canonical label is still a changed fact and is
compared like every other source-owned field. A populated database cannot mix source commits; a new
source version requires an explicit rebuild or a separate database.

Every run records per-table source, inserted, updated, unchanged, rejected/conflicted and final
scoped counts. `updated` remains explicit and is normally zero under the reject-on-change policy.
Failed runs may report attempted/source counts but never claim rolled-back rows as final writes.
Every owned terminal transition must update exactly one still-running manifest; a missing transition
is an integrity error rather than a silently accepted zero-row update. Scope rows are durable evidence
and use the default non-cascading foreign key, so deleting a parent run cannot erase them implicitly.

## Consequences

Every identical rerun creates audit evidence while changing no source-derived rows. A process that
dies after committing `running` is recovered honestly by the next lock owner. The internal database
may contain four tournaments, but the public `/baseline` and `/shots` query scope remains WC 2022
until the unresolved publication question is cleared.

The serving and operator connection paths must be configured deliberately on Neon: pooled for the
Railway API, direct for migration and ingestion commands. Other PostgreSQL hosts are not classified
by this Neon-specific hostname guard; their compatibility remains the operator's responsibility.

Temporary staging tables have transaction-local key indexes because the measured relation grain is
1,227,110 rows; they disappear with the ingestion connection and are not durable query indexes.
