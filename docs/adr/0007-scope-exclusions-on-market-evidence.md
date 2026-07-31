# ADR 0007: Scope exclusions decided on job-market evidence

## Status

Accepted — 2026-07-31

## Context

Scope decisions on a portfolio project are usually made from general industry advice, which is a poor
guide because it describes the whole software market rather than the specific segments being targeted.
A scan of 30 real postings across clubs, data providers, betting/trading and general applied-ML
produced frequency data specific to these segments
([`research/job-market-methodology.md`](../research/job-market-methodology.md)).

Several widely-recommended technologies turned out to be absent from this market, and one assumption
carried in earlier planning was measurably wrong.

## Decision

The following are **out of scope**, each for a stated evidential reason:

| Excluded | Evidence | Reasoning |
|---|---|---|
| **dbt** | **0 of 30 postings** | Earlier planning cited a general data-engineering survey reporting dbt in ~61% of postings. That figure does not describe this market. Removed. |
| **Orchestration (Airflow, Dagster)** | 1 essential, 1 desirable | Appears mostly as an existing stack detail rather than a candidate requirement. High setup cost, negligible signal. |
| **Data warehouse (Snowflake, BigQuery)** | 2 essential, 3 desirable | Same reasoning; PostgreSQL covers everything this project needs. |
| **AWS / Azure in the core** | — | See ADR 0006. |
| **Scout Explorer, Action Value Lab, 360 Spatial** (v1 phases 3–5) | — | Do not fit alongside a defensible core; each would be shallow. |
| **Kubernetes, microservices, feature stores, Kafka, multiple data providers, complex auth, custom design system** | — | No requirement observed; substantial complexity. |

Two further calibrations from the same evidence, recorded here because they changed emphasis rather
than scope:

- **TypeScript is essential in exactly 1 of 30 postings.** It stays in the project because it is
  already in the profile and the interface is the strongest differentiator — but the portfolio is
  **not** centred on it, since that would optimise for a single role family.
- **Football domain knowledge is mostly desirable** (4 essential, 7 desirable), while **written
  communication to non-technical audiences is essential in 21 of 30**. Effort is weighted accordingly:
  communication is a cross-cutting mandatory requirement, football depth is demonstrated through the
  stakeholder summary rather than pursued as a separate study track.

## Alternatives considered

- **Include dbt anyway, for keyword coverage:** rejected — zero observed demand in these segments, and
  a shallow inclusion invites a question that cannot be answered well.
- **Include a warehouse to demonstrate "scale":** rejected — the dataset is ~230 matches. A warehouse
  would be theatre, and transparently so.
- **Follow general industry advice rather than segment evidence:** rejected — that is precisely the
  error this ADR corrects.

## Consequences

- Effort concentrates on requirements that actually recur: Python, communication, SQL, statistics and
  uncertainty, deployment.
- Data-engineering postings that hard-require dbt or a warehouse are a partial match. Accepted.
- The exclusion reasoning is itself interview material: choosing scope from measured demand rather
  than from a technology wish list is a defensible engineering argument.
- The frequency data has a shelf life. It is re-scanned before each application wave.

## Review trigger

A re-scan shows any excluded technology appearing in a materially larger share of target postings, or
a specific role reaching final stages requires one.
