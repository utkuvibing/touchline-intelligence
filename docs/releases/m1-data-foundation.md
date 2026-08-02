# From nested football events to a trustworthy relational dataset

## Release status

M1 Data Foundation is technically complete. A pinned 465-file StatsBomb Open Data snapshot rebuilds
to the same documented 230-match, four-tournament PostgreSQL cohort, and an identical rerun changes
no source facts. This is an internal data-engineering release: the unresolved logo-asset and public
row-level redistribution questions in [`DATA_SOURCE.md`](../../DATA_SOURCE.md) still block broader
publication claims. Data provided by StatsBomb.

## Problem, decision, result

Nested event JSON is convenient to inspect but makes duplicate prevention, joins, missingness and
source drift easy to mishandle. The project therefore preserves the pinned raw-file evidence while
promoting stable entities into a constrained relational model. Ordered migrations define table
grain and integrity; ingestion stages source rows, rejects changed facts under a stable key, and
commits source data, reconciliation and a succeeded run manifest atomically.

The clean rebuild produced 230 matches, 843,050 events, 1,227,110 directed event relations and 5,829
typed shots across WC 2018, Euro 2020, WC 2022 and Euro 2024. The independent audit reconciled all 16
persisted source grains, reported no errors and found zero invariant violations. A subsequent
identical run inserted, updated and rejected zero rows in every source table.

## For a coach or non-technical stakeholder

This release establishes that the selected historical match data can be rebuilt consistently: the
same pinned source files produce the same reconciled counts and relational records, so analysts can
start from a traceable shared dataset rather than separate spreadsheets or ad-hoc extracts. It is
trustworthy for describing the recorded events in this fixed four-tournament cohort and for checking
that the data loaded as expected.

It does not say which chances were better, predict whether a future shot will be scored, evaluate
player or team performance, or establish appearances, minutes played, or tracking-based movement.
There is no xG or other model in this release; lineup membership and embedded freeze frames must not
be interpreted as minutes or continuous tracking. Do not use these historical records as predictions
or as a decision recommendation. Do not expand the public row-level data or redistribute it while
the open StatsBomb logo-asset and public row-level redistribution questions remain unresolved.
Data provided by StatsBomb.

## Evidence map

- Schema and ERD: [`docs/SCHEMA.md`](../SCHEMA.md)
- Source revision, coverage and data dictionary: [`DATA_SOURCE.md`](../../DATA_SOURCE.md)
- Ingestion conflict and transaction policy: [ADR 0010](../adr/0010-idempotent-ingestion-and-manifest-lifecycle.md)
- Quality report: [`reports/wp1.4-core-cohort.txt`](../../reports/wp1.4-core-cohort.txt)
- SQL findings and measured plans: [`docs/analysis/wp1_5_sql_analysis_pack.md`](../analysis/wp1_5_sql_analysis_pack.md)
- Clean-rebuild protocol: [`docs/reproducibility/wp1_6_clean_rebuild.md`](../reproducibility/wp1_6_clean_rebuild.md)
- Machine-readable release evidence: [`reports/wp1.6-clean-rebuild.json`](../../reports/wp1.6-clean-rebuild.json)

## SQL findings worth discussing

The ten-query pack keeps each output grain explicit. It distinguishes squad membership from
appearance evidence, scopes the `LAG` sequence exercise inside a match and possession, and handles
NULLs deliberately instead of relying on three-valued filtering. Two representative plans were
measured on the full cohort. A proposed event-type index improved one manual aggregate but was
rejected because it added about 5.6 MiB plus write maintenance without serving a recurring or
production workload.

## Five-minute terminal demo

The commands below form the short demo. The destructive first command is local-only and must point
at the disposable development database, never a shared or production database.

```bash
uv run poe ingest --offline --reset
uv run poe quality
uv run poe ingest --offline
uv run poe reproducibility-fixture
```

During the walkthrough:

1. Show that migrations 0001–0007 are applied to an empty schema.
2. Open clean-build manifest `a30ac223-d7a0-4386-800a-06d1ef249645` and connect its source counts to
   the quality report.
3. Run one representative SQL query and state its result grain before reading the result.
4. Open rerun manifest `94107ada-fb27-40eb-b322-175ab6c10541` and show that every source table has
   zero inserts/updates/rejects and unchanged counts equal to source counts.
5. Finish with the limitations below rather than implying model or publication claims.

The checked counts and hashes in the machine-readable report are the durable terminal capture; a
screenshot is not used as numerical evidence because it cannot be rerun or diffed.

## Limitations

- There is no shot-quality model yet. All current rates and maps describe recorded outcomes.
- Provider xG is excluded from storage to protect the future feature boundary.
- Lineup membership is not an appearance or minutes-played denominator.
- Embedded shot freeze frames are neither StatsBomb 360 nor continuous tracking data.
- The tournament holdout planned for M2 changes competition composition and time together; it is
  not called a pure temporal holdout.
- Public row-level scope is not expanded while the two source-publication questions remain open.

## Interview and CV wording

Draft CV claim: “Designed a PostgreSQL football-event schema and idempotent ingestion pipeline over
a pinned 230-match StatsBomb Open Data cohort, enforcing provenance, relational constraints,
transactional conflict rejection, count reconciliation and automated data-quality checks.”

Interview story: raw nested JSON could silently duplicate or drift between analyses. The project
kept immutable source references but made PostgreSQL the query contract, with explicit grains,
foreign keys, source-key conflict detection, durable run manifests and independent reconciliation.
The result is a cohort that rebuilds from empty state and reruns without changing facts, giving M2
a traceable input contract rather than an informal notebook extract.
