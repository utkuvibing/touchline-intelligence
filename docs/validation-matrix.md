# WP5.4 validation matrix

This is the authoritative executable validation matrix for WP5.4. It records the minimum tier for
each check. The tier principle is deliberate: **pull requests prove code health; milestones prove
scientific and contract integrity; releases prove reproducibility and deployability.**

Run the entry points with `uv run poe validation-pr`, `uv run poe validation-milestone`, and
`uv run poe validation-release`. They compose existing commands; they do not copy test logic.
CI continues to run the PR tier's backend and frontend commands in their separately provisioned
jobs. Wiring the combined local entry point into CI is deferred until it can preserve that split
without duplicating dependency setup or reducing either job's evidence.

| Check | Minimum tier | Command | Prerequisites and boundary |
|---|---|---|---|
| Backend formatting, lint, types, unit and fixture integration tests | Pull request | `uv run poe check` | `TOUCHLINE_DB_URL` must be a loopback PostgreSQL URL. Fixture tests may write only isolated local schemas. |
| Frontend lint, types and tests | Pull request | `npm --prefix frontend run lint`, `typecheck`, `test` | Node dependencies installed. |
| Full-cohort acceptance | Milestone | `uv run pytest -m full_cohort` | Clean tree; inherited local `TOUCHLINE_DB_URL` for the PR tier and local populated `TOUCHLINE_FULL_COHORT_DB_URL`. Marked full-cohort checks are read-only. |
| Fixture reproducibility | Milestone | `uv run poe reproducibility-fixture` | Same local database prerequisites; no sealed outcomes. |
| Frontend production build | Milestone | `npm --prefix frontend run build` | Clean tree and frontend dependencies installed. |
| Packaged serving bundle | Milestone | `uv run poe wp3-1-docker-acceptance` | Clean tree and Docker. No deployment target is contacted. |
| Retained mutation sentinels | Milestone | Pending WP5.4 sentinel-selection slice | Exactly 15 active sentinels; until registered, the milestone entry point exits non-zero before dispatch. |
| Broader current-candidate mutation sweep | Release | Pending WP5.4 release-sweep slice | Clean tree and all mutation prerequisites. Missing, invalid, ambiguous, missed, or unrun high-risk cases block release. |
| Artifact and provenance verification; clean image/build; local-to-production golden parity; deployed smoke; rollback/recovery; dependency and independent review | Release | Pending release-sweep slice plus existing release commands | Release-owned, documented credentials and targets. The tier runner never permits a database URL outside loopback, so it cannot write to a deployed database. |

## Fail-closed operation

The runner checks all required prerequisites before launching any command. A missing database,
non-loopback database URL, dirty tree where required, unavailable mutation control, or failed child
command is a failure. An optional test that is not part of a tier cannot be counted toward that
tier. The current milestone and release entry points intentionally refuse to run until their
mutation controls are implemented; a dry run is available for inspection.

PostgreSQL URI query parameters that can reroute libpq (`host`, `hostaddr`, `port`, or `service`)
and multi-host authorities are rejected even when their first host names loopback. Child commands
do not inherit ambient libpq routing variables such as `PGHOSTADDR` or `PGSERVICE`. Scoping is
command-aware: every PR/code-health command receives neither `TOUCHLINE_FULL_COHORT_DB_URL` nor
`TOUCHLINE_FULL_SOURCE`, even inside milestone or release plans. Only the explicit full-cohort
command receives `TOUCHLINE_FULL_COHORT_DB_URL`; no command receives `TOUCHLINE_FULL_SOURCE`.

The matrix does not authorize model training, ingestion, sealed-outcome access, or deployment
changes. Existing database commands retain their own safety controls; this runner only invokes
validation commands against loopback databases.
