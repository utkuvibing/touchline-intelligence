# Phase 1 — Data Foundation

**Estimate:** 65–85 hours, roughly 4–6 weeks at 15–20 hours/week  
**Release:** reproducible StatsBomb-to-PostgreSQL data engineering case study  
**Scope:** start with one documented competition/season slice; expand only after reliability gates pass.

## Goals and user value

This phase turns nested source JSON into a trustworthy relational foundation. Analysts gain stable entities and queryable events; model builders gain reproducible, tested inputs; a football organization gains provenance, duplicate prevention, explicit data coverage, and quality reports rather than unverified notebook extracts.

The phase also builds the developer's missing SQL and relational-modelling foundation. Raw JSON remains traceable source evidence, but PostgreSQL becomes the product's query and serving contract.

## Deliverables

### Mandatory

- dated review record for the StatsBomb Open Data README, licence/usage conditions, attribution, logo, and redistribution implications;
- `DATA_SOURCE.md` or equivalent describing event data, selected 360 freeze frames, and why neither should be overstated as full tracking;
- source inventory for the selected competition/season: file counts, match coverage, available event/lineup/360 types, update metadata, and checksums/commit reference;
- data dictionary and entity-relationship diagram;
- ordered PostgreSQL migrations with keys, relationships, types, uniqueness and check constraints;
- command-line ingestion path from source files to PostgreSQL;
- ingestion run/manifest table recording source version, scope, timestamps, counts, status, and errors;
- idempotent reruns and duplicate prevention at database level;
- schema/source validation and actionable errors for malformed or unsupported files;
- data-quality suite and generated quality report;
- deterministic small fixture data for tests without live-network dependence;
- 8–12 analytical SQL queries with explanations and checked results;
- clean setup/load instructions and one end-to-end integration test.

### Recommended

- quarantine/reporting path for invalid records rather than silently dropping them;
- basic indexes justified by measured query plans;
- incremental load for newly available matches after full-scope loading works.

### Optional

- expanded competition coverage; simple data-profile page. Do not add an orchestration platform.

## Technical work

### WP1.1 — Rights, source, and domain orientation (6–9 hours)

Read the current official repository README, linked licence, and data specification. Record date, version/commit, required attribution locations, and restrictions relevant to the repository, live app, reports, screenshots, model artifacts, and data redistribution. Add the required source statement and logo asset/link according to current rules before publishing.

Manually inspect competition, match, lineup, event, and available 360 JSON for at least two matches. Make a coverage table. Define coordinate orientation, period/timestamp semantics, identifiers, nullability, event ordering, possession fields, own goals, extra time, shootouts, substitutions, and sparse event-specific attributes. Record unknowns instead of guessing.

### WP1.2 — Relational model (10–14 hours)

Draw entities and cardinalities before migrations. A reasonable initial core includes competitions, seasons, competition-seasons, matches, teams, players, match-team, lineups/appearances, events, related-event links, and typed high-value event detail. Preserve source IDs. Use JSONB only for sparse residual attributes while promoting fields required by Phase 2 queries to typed columns.

Review normalisation, foreign-key behaviour, nullable fields, enum/reference tables, uniqueness, and deletion policy. Create migrations plus a rollback/rebuild strategy for local development. Do not optimize indexes before representative queries exist.

### WP1.3 — Parsing and idempotent ingestion (16–21 hours)

Separate source parsing/validation, domain mapping, and persistence enough to test each. Load the smallest dependency units first. Use database transactions at a defined scope, deterministic identifiers/source keys, and conflict behaviour that cannot duplicate matches/events on rerun. Record manifest counts and failures. A partially failed load must not masquerade as success.

Prove three cases: first load, identical rerun, and source scope containing one new match. Define whether changed source records are updated, rejected, or require a new dataset version; document the choice.

### WP1.4 — Data quality and reconciliation (12–16 hours)

Test database constraints and football/data invariants. Examples: source ID uniqueness; event belongs to the correct match/team/player when present; nonnegative/valid time and coordinate bounds; exactly two match teams under the scoped rules; event count reconciliation; valid outcome/category references; lineup/event player coverage; no orphan related events; expected file-to-table count tolerances.

Generate a report separating errors, warnings, coverage, exclusions, and known source limitations. Sample records manually against JSON. Do not “clean” surprising football events without evidence.

### WP1.5 — SQL analysis pack (12–15 hours)

Write queries directly in SQL for match/event counts, competition coverage, team results, shot counts, player minutes/appearances, event-type distribution, missingness, home/away or score checks, and one sequence/window-function exercise. Explain joins, grouping level, grain, null behaviour, and expected output. Use `EXPLAIN` for at least two representative queries before and after only justified indexes.

### WP1.6 — Reproducibility and release (9–10 hours)

Run migrations and the scoped load from a clean database using documented commands. Execute the end-to-end test and report generation. Add diagrams, SQL findings, limitations, attribution, screenshots, and a short demo. Pin the ingestion manifest used by Phase 2.

## Skills demonstrated

- SQL, joins, aggregations, windows, constraints, and query plans;
- relational data modelling and migrations;
- Python parsing, typed validation, transactions, and CLI engineering;
- data engineering, provenance, idempotency, and reconciliation;
- automated integration and data-quality testing;
- football event-data literacy and evidence boundaries;
- licensing/attribution diligence and technical documentation.

## Learning objectives

Explain from first principles without AI:

- why relational tables and constraints add value beyond raw JSON;
- table grain, primary keys, foreign keys, natural/source keys, and many-to-many relationships;
- normalisation trade-offs and why some sparse source attributes may remain JSONB;
- inner versus left joins and how a join can accidentally multiply rows;
- how `NULL` affects comparisons and aggregates;
- transactions and what should happen on partial ingestion failure;
- why idempotency matters and how uniqueness/upserts enforce it;
- the difference between source validation, schema constraints, reconciliation, and football-domain checks;
- why an index can speed reads but add write/storage cost;
- the distinction between event data, 360 freeze frames, and continuous tracking;
- what the selected Open Data slice can and cannot support.

## Manual implementation requirements

| Component | Why manual involvement matters | Knowledge built | Sufficient manual level |
|---|---|---|---|
| Raw-match inspection and field notes | generated mappings can hide misunderstood semantics | football event structure and source skepticism | inspect two matches and annotate at least 20 important fields/edge cases |
| ER model and three migrations | schema decisions shape every later phase | grain, cardinality, constraints, migration lifecycle | draw the ERD; personally write/rewrite core match, player/lineup, and event DDL |
| Representative ingestion transaction/upsert | idempotency must be understood, not asserted | transactions, conflicts, failure recovery | implement or rewrite one match+events load path and explain rerun behaviour |
| 8–12 SQL queries | pandas/ORM delegation would bypass the key skill gap | joins, grouping, windows, query plans | author queries without ORM; AI may review after first working attempt |
| Five data-quality rules | domain invariants require judgment | validation layers and false positives | define expected failure examples and implement at least five checks |

Manual work is sufficient when the developer can alter a schema/query, predict affected results, and diagnose a failing constraint. Hand-writing repetitive mappings is not required.

## AI-agent delegation

Agents may draft Pydantic/schema classes, repetitive field mappings, migration boilerplate after the ERD, CRUD/repository functions, fixture builders, test parameterization, diagrams, and documentation formatting. Agents may suggest indexes only with a measured query and plan.

Review protocol:

1. map every generated field to official source documentation or an observed sample;
2. inspect generated SQL and constraints directly, not only ORM models;
3. test empty, duplicate, malformed, partial-failure, and rerun cases;
4. reconcile counts to source files and spot-check records;
5. remove silent exception handling or silent row dropping;
6. make a targeted manual schema/query/transaction change and rerun checks;
7. explain the data path and known limitations without the agent.

## Technical interview readiness

- How did you model heterogeneous StatsBomb events relationally without losing source fidelity?
- What is the grain of your events, lineups, and player-minute tables?
- How do you guarantee an ingestion rerun does not create duplicates?
- What happens if one match fails halfway through loading?
- How did you choose between typed columns and JSONB?
- Give an example of a join that inflated results and how you detected it.
- Which data-quality checks are database constraints versus pipeline tests, and why?
- How did you validate that loaded records match the source?
- Which indexes did you add, and what evidence justified them?
- What can StatsBomb 360 tell you that event data cannot, and why is it not tracking data?
- What attribution and data-sharing checks did the project require?

## Testing and validation

- **Unit tests:** source parsers, coordinate/time conversion, optional/nested fields, mapping functions, manifest state transitions.
- **Integration tests:** migrations on empty PostgreSQL; one complete fixture match load; foreign keys/constraints; transaction rollback; first load and rerun.
- **Data-quality tests:** uniqueness, referential integrity, bounds, category validity, two-team/match assumptions, event/file/table reconciliation, orphan links, coverage and missingness thresholds.
- **Model validation:** not applicable; freeze and identify the future modelling dataset rather than training early.
- **Manual acceptance:** compare sampled competition, match, lineup, shot, substitution, and related-event records against raw JSON; run SQL pack and inspect plausible totals/grains.
- **Reproducibility:** from an empty volume, one documented command sequence recreates schema, scoped data, manifest, and quality report with equal counts/checksums (excluding timestamps).

Avoid tests that merely assert a dataframe is nonempty. Each test protects a named contract or invariant.

## Portfolio artifact

- **English write-up:** “From nested football events to a trustworthy relational dataset,” including ERD, idempotency design, quality findings, and limitations.
- **Demo:** terminal/database walkthrough showing empty database, load, quality report, representative SQL, and unchanged counts after rerun.
- **GitHub deliverable:** versioned migrations, ingestion command, fixture tests, SQL analysis pack, data dictionary, source/attribution record, and quality report.
- **Draft CV claim:** “Designed a PostgreSQL football-event schema and idempotent Python ingestion pipeline for a documented StatsBomb Open Data slice, enforcing provenance, relational constraints, count reconciliation, and automated data-quality checks.”
- **Interview story (problem–decision–result):** Problem—nested, heterogeneous JSON was easy to explore but could silently duplicate or drift across analyses. Decision—preserve source files while building constrained relational entities, manifests, transactional upserts, and reconciliation tests. Result—the same scoped dataset can be rebuilt from empty state and rerun without count changes, giving later models a traceable input contract.

Replace “documented slice” with measured match/event counts only after the release report records them.

## Definition of done

- Current official terms were reviewed, dated, and implemented in repository/release attribution; publication is blocked if this check is stale or unresolved.
- The selected competition/season and exclusions are explicitly inventoried.
- A clean PostgreSQL database migrates and ingests through documented commands.
- Loading the exact same source twice produces zero duplicate source IDs and unchanged entity/event counts.
- A new-match scenario adds only expected records; a malformed/partial scenario fails visibly and preserves defined transaction guarantees.
- Required foreign keys, uniqueness, and coordinate/time/category checks pass.
- Automated reconciliation matches source counts within documented, justified tolerances.
- 8–12 reviewed SQL queries return results at their stated grain.
- No standard test requires network access or the full dataset.
- The developer can draw the schema and explain one complex join, one upsert, one quality failure, and the Open Data/360/tracking distinction unaided.
- Write-up, demo, GitHub state, CV claim, and interview story exist.

## Risks and scope cuts

| Risk | Response |
|---|---|
| trying to perfectly model every event subtype | type only Phase 2/near-term fields; preserve residual payload with documentation |
| copying a generated schema without understanding grain | ERD/cardinality review and manual DDL/query requirements |
| silent source changes | capture source commit/checksums and manifest; treat changes explicitly |
| confusing missing with zero/false | data dictionary, nullable types, missingness report, source spot checks |
| broad data coverage overwhelms tests | keep one competition/season until all reliability gates pass |
| attribution or redistribution mistake | dated pre-release checklist; link official terms; do not commit raw data by default |
| building orchestration prematurely | use one explicit CLI and scheduler only when a real recurring job exists |

Cut first: expanded competitions, admin/profile UI, incremental fetching, advanced indexes, materialized views, generalized plugin architecture. Then reduce typed event subtypes while preserving Phase 2 shot fields and source payload. Never cut provenance, idempotency, constraints, fixture tests, reconciliation, or attribution.

## Dependencies

- Phase 0 definition of done;
- working local PostgreSQL and migration/test commands;
- access to the official StatsBomb Open Data repository and current terms/specification;
- selected initial competition/season after a coverage review;
- enough local storage for the scoped source and database.

## Estimated effort

**65–85 hours / 4–6 weeks.** Approximate allocation: 10–14 hours source/domain learning, 10–14 schema design, 16–21 ingestion, 12–16 testing/quality, 8–12 SQL practice, and 7–8 release/documentation. At 15 hours/week, use the upper duration and do not expand data coverage.
