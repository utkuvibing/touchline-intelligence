# WP1.6 clean-rebuild reproducibility protocol

WP1.6 supplies a small, deterministic proof of the production data path. It is deliberately
separate from the cached real-source acceptance run: CI and ordinary developer tests must never
need a network download or the 465-file StatsBomb cache.

## What is implemented now

The committed fictional fixture at `data/fixtures/statsbomb/` has the same file layout and enough
structure to traverse the production parsers, migrations, idempotent ingestion runner, lifecycle
manifest and independent quality inspector. `manifest.json` pins the SHA-256 of every fixture JSON
file and requires exactly that file set. It is validated before the integration proof is useful;
editing a fixture byte therefore requires an intentional manifest update and test review.

Run the focused proof against the disposable local PostgreSQL database:

```bash
docker compose -f infra/docker-compose.yml up -d
uv run poe reproducibility-fixture
```

The integration portion is skipped when `TOUCHLINE_DB_URL` is absent. The byte-manifest test is
not skipped and remains network-free. The proof creates a dedicated empty PostgreSQL schema,
applies the packaged migrations `0001` through `0007`, ingests the fixture with
`StatsBombSource(..., offline=True)` through `run_ingestion`, commits it, and opens a separate
connection for `quality.inspect`. It then drops that schema, repeats the clean migration and load,
and requires identical canonical snapshots and quality evidence.

The canonical snapshot includes every source-owned table, all nonvolatile ingestion-manifest fields
and scope rows, and all nonvolatile migration-ledger fields. It compares values ordered by their
canonical JSONB text representation. Its complete exclusion set is only execution identity/time:
`ingestion_runs.run_id`, `owner_token`, host/pid and start/phase/finish timestamps;
`ingestion_run_scopes.run_id`; and `schema_migrations.applied_at`. Source facts, source counts,
source commit/scope, manifest state, migration versions and migration checksums must be equal. The
test also requires every first-build source row to be inserted and every post-commit quality
invariant count to be zero. The fixture has deliberately incomplete future-model shot fields, so
its named quality errors are retained as evidence rather than silently reclassified as a successful
real-cohort audit.

## Production full-cohort evidence

The cached four-tournament cohort was rebuilt from an empty local database on 2026-08-02 with:

```bash
uv run poe ingest --offline --reset
uv run poe quality
uv run poe ingest --offline
```

The destructive clean build produced succeeded manifest
`a30ac223-d7a0-4386-800a-06d1ef249645`. All source-derived tables began empty; each table reported
`inserted = source = final_scoped`, with zero updated, rejected or unchanged rows. The independent
read-only audit then reconciled all 16 persisted source grains, reported no errors and found zero
invariant violations. An identical non-reset rerun produced manifest
`94107ada-fb27-40eb-b322-175ab6c10541`; every table reported zero inserts, updates and rejects, and
`unchanged = source = final_scoped`.

The complete machine-readable evidence, counts, migration checksums and report hashes are committed
in [`reports/wp1.6-clean-rebuild.json`](../../reports/wp1.6-clean-rebuild.json). The generated quality
reports remain [`reports/wp1.4-core-cohort.json`](../../reports/wp1.4-core-cohort.json) and
[`reports/wp1.4-core-cohort.txt`](../../reports/wp1.4-core-cohort.txt); their manifest reference now
points to the clean-build run.

The committed provenance manifest pins the **input** source bytes: it must name the source commit,
scope and a SHA-256 per file, and its file count must be 465. A successful ingestion manifest pins
the **database run**: it records the same canonical source commit, exact relational scope and
attempted/source counts. Phase 2 (M2) experiment or artifact records must cite both: the exact
successful run UUID and the canonical source/scope/provenance fingerprint. WP1.6 pins the clean-build
run `a30ac223-d7a0-4386-800a-06d1ef249645`; replacing it later is a deliberate evidence update, not
an implicit “latest run” lookup. The UUID is required for traceability but is deliberately not a
reproducibility checksum; a fresh clean rebuild generates a new UUID and timestamps while preserving
source facts, migration checksums and canonical counts.

## Boundaries and release gates

- This is a reproducibility and data-engineering proof, not model evaluation and not permission to
  redistribute source data. The committed fixture is fictional.
- The full source remains StatsBomb Open Data at pinned commit
  `b0bc9f22dd77c206ddedc1d742893b3bbe64baec`, with the fixed balanced tournament scope WC 2018,
  Euro 2020, WC 2022 and Euro 2024.
- Data is provided by StatsBomb. Attribution remains mandatory in repository, reports and any
  permitted published output.
- The unresolved Media Pack/logo and public row-level redistribution questions in `DATA_SOURCE.md`
  remain publication gates. WP1.6 does not clear either one.
