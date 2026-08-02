# Touchline Intelligence Platform

Football research and decision-support built on [StatsBomb Open Data](https://github.com/statsbomb/open-data)
— a validated relational dataset, a calibrated shot-quality model, and an analyst interface, with the
evidence trail that makes every number defensible.

**Live:** [https://touchline-intelligence.vercel.app](https://touchline-intelligence.vercel.app) · API: [https://touchline-intelligence-production.up.railway.app/docs](https://touchline-intelligence-production.up.railway.app/docs)

> **Status: M0 (Walking Skeleton) complete.**
> There is **no shot-quality model yet**, and **no performance claim anywhere in this repository or
> on the deployed site has been evaluated**. M0 proved one thing end to end — data → PostgreSQL →
> API → UI → deployment — and deliberately makes no modelling claims. The map shows recorded shots
> and recorded outcomes; the conversion rate is a description of the loaded data, not a prediction.
> See [`docs/PLAN.md`](docs/PLAN.md) for what each milestone adds.

M1 Data Foundation is complete. WP1.1's dated source review, measured coverage, data dictionary,
and two unresolved publication gates are recorded in [`DATA_SOURCE.md`](DATA_SOURCE.md); milestone
completion does not clear those gates. WP1.2 through WP1.6 delivered the relational schema,
idempotent full-cohort ingestion, quality report, SQL analysis pack and reproducibility release.
The final clean rebuild, no-op rerun, mutation verification and independent Sol review passed.

## Documentation

| Document | What it covers |
|---|---|
| [`AGENTS.md`](AGENTS.md) | **Start here.** Current state, non-negotiable rules, and where each detail lives |
| [`docs/PLAN.md`](docs/PLAN.md) | Milestones, data scope, validation design, what must be defensible before a claim is used |
| [`docs/TARGETING.md`](docs/TARGETING.md) | Role fit tiers, employers, artifact↔requirement mapping |
| [`DATA_SOURCE.md`](DATA_SOURCE.md) | Source revision, dated terms review, current coverage inventory, and data dictionary |
| [`CONTEXT.md`](CONTEXT.md) | Canonical project domain language |
| [`docs/SCHEMA.md`](docs/SCHEMA.md) | ERD, table grain, migrations, constraints, and validation boundaries |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Vercel + Railway + Neon setup, environment variables, smoke test |
| [`docs/adr/`](docs/adr/) | Architecture decision records |
| [`docs/research/job-market-methodology.md`](docs/research/job-market-methodology.md) | How scope was decided from observed job-posting demand |
| [`docs/experiments/README.md`](docs/experiments/README.md) | Experiment record format and comparison rules |

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | ≥ 0.11 | Manages Python itself; no separate Python install needed |
| Node.js | 24 (see `.nvmrc`) | |
| Docker Desktop | any current | Required for the local database |

Python is pinned in `.python-version` and resolved by uv. Dependencies are locked in `uv.lock` and
`frontend/package-lock.json`; installs are deterministic from those files.

## Setup

```bash
git clone <repo> && cd "football ml"
```

```bash
cp .env.example .env
```

```bash
uv sync
```

```bash
cd frontend && npm ci && cd ..
```

```bash
docker compose -f infra/docker-compose.yml up -d
```

The database exposes host port **5433**, not 5432, so it cannot collide with a PostgreSQL already
installed on the machine. `.env.example` matches this.

## Commands

Backend commands run through [poethepoet](https://poethepoet.natn.io/), which is a Python dev
dependency — there is nothing extra to install on Windows.

| Command | Does |
|---|---|
| `uv run poe check` | format check → lint → type check → tests. **This is what CI runs.** |
| `uv run poe format` | Apply formatting |
| `uv run poe lint` | Ruff lint |
| `uv run poe typecheck` | mypy (strict) |
| `uv run poe test` | pytest (integration tests skip unless the database is up) |
| `uv run pytest -m integration` | Integration tests against the running PostgreSQL |
| `uv run poe migrate` | Apply pending ordered PostgreSQL migrations (Neon requires its direct URL) |
| `uv run poe ingest` | Idempotently merge the fixed four-tournament core cohort (Neon requires its direct URL) |
| `uv run poe ingest --reset` | Destructively rebuild locally, then load the fixed core cohort |
| `uv run poe reproducibility-fixture` | Check fixture bytes and prove two isolated, network-free clean rebuilds agree (requires local PostgreSQL for the integration half) |
| `uv run poe api` | Run the API at http://localhost:8000 |
| `uv run python scripts/verify_tests_fail.py` | Break each protected behaviour once and confirm the tests catch it |
| `cd frontend && npm run dev` | Next.js dev server |
| `cd frontend && npm test` | Vitest |
| `cd frontend && npm run typecheck` | tsc |
| `cd frontend && npm run lint` | ESLint |
| `uv run python scripts/smoke_deployed.py --api ... --frontend ...` | Smoke-test a deployed instance |

### Ops endpoints

- `GET /health` — liveness. Never touches the database, so a database blip does not cause the
  platform to restart a healthy process.
- `GET /ready` — readiness. Does touch the database, because an instance that cannot query is not
  ready to serve. Reports the exception class name only, never connection details.

## Testing approach

Tests protect named contracts, not line coverage. Coverage percentage is not an acceptance criterion.

`scripts/verify_tests_fail.py` exists because a green suite proves the tests pass, not that they
would fail if the behaviour broke. It has already caught three tests that passed for the wrong
reason and led to all three being rewritten.

The ordinary suite uses committed fictional fixtures and never downloads StatsBomb data in CI.
With the pinned 465-file cache present, the slow real-source acceptance proof is opt-in:

```bash
TOUCHLINE_FULL_SOURCE=1 uv run pytest backend/tests/test_full_cohort_acceptance.py
```

It exercises populated-WP1.2 upgrade, full reconciliation, the WC 2022 public boundary, provider-xG
absence, and an identical no-op rerun whose source-owned columns are fingerprinted across all four
tournaments and all 16 source-derived tables.

WP1.6 adds a focused two-clean-build fixture proof, separate from the full-source acceptance test.
It starts an isolated schema from no tables, applies production migrations, runs production ingestion
against fictional committed bytes in offline mode, runs independent quality inspection, then rebuilds
again and compares source facts and migration checksums. The fixture manifest, full-cohort clean
rebuild and Phase 2 input pin are documented in
[`docs/reproducibility/wp1_6_clean_rebuild.md`](docs/reproducibility/wp1_6_clean_rebuild.md).
The M1 technical and stakeholder release artifact is
[`docs/releases/m1-data-foundation.md`](docs/releases/m1-data-foundation.md).

## Repository layout

```text
backend/src/touchline/   Python package — FastAPI, config, later: ingestion, features, modelling
backend/tests/           pytest
frontend/                Next.js + TypeScript, Vitest
infra/                   docker-compose for local PostgreSQL
scripts/                 documented developer entry points
docs/                    plan, targeting, ADRs, research, experiment rules
```

## Data ingestion and schema

```bash
uv run poe ingest --reset
```

Loads the fixed WC 2018, Euro 2020, WC 2022 and Euro 2024 cohort: 230 matches, 54 teams,
1,989 players, 843,050 events, 460 lineups, 11,062 lineup memberships, 39,262 possessions,
1,227,110 directed event relations, 5,829 typed shots, and 78,866 actors from shot-embedded
freeze frames.

**The source snapshot is pinned to a commit SHA, not `master`.** Open Data is a live repository, so
a load against `master` would drift and the measured counts in ADR 0004 would stop meaning anything.
Every load writes a provenance record — source commit plus a SHA-256 for each file read — to
[`data/provenance/`](data/provenance/), which is committed so another machine can prove it received
identical bytes. Downloaded files are cached under `data/statsbomb/<sha>/` (git-ignored);
`--offline` fails rather than downloading.

**The production loader is idempotent and reject-on-change.** Each invocation has a durable run
manifest. Source rows are staged with PostgreSQL `COPY`; identical source keys are no-ops, while a
changed source-derived fact under the same pinned commit raises `SourceConflictError` rather than
silently rewriting evidence. Source changes, exact scoped reconciliation, and the successful
manifest transition share one transaction. Handled failures roll back that transaction and record
a sanitized failed status separately. A session advisory lock serializes runs and lets a later
owner recover a genuinely abandoned manifest without misclassifying an active owner.

On Neon, migration and ingestion commands require the **direct** connection URL and reject a known
`-pooler` hostname before opening a connection or writing any state. Railway's serving API should
keep Neon's pooled URL; an operator temporarily supplies the direct URL to the same
`TOUCHLINE_DB_URL` variable for these commands. No second database environment variable is used.

**The caller owns the transaction, and reconciliation happens before the commit.** The flow is
reset → load → read counts back → reconcile against the source → commit. Counts are read inside the
transaction, against rows that are written but not yet durable, so a mismatch rolls the whole load
back. Nothing in the loader module commits: committing first and reporting afterwards would make
reconciliation a description of data already kept.

**The normalized source-shaped schema is managed through seven ordered, hand-written SQL
migrations.** Stable shared event fields are typed relational columns; heterogeneous non-shot
type-specific structures remain sanitized JSONB. Lineup memberships are match-team squad records,
not proof that a player appeared or played any duration. Directed related-event references preserve
source direction and ordering. Embedded shot freeze frames are event snapshots, not StatsBomb 360
or continuous tracking. Applied migration SQL is checksum protected. See
[`docs/SCHEMA.md`](docs/SCHEMA.md) and
[ADR 0009](docs/adr/0009-full-relational-event-and-lineup-scope.md).

No generic event rows are exposed by the public API. Although the internal database holds four
tournaments, `/baseline` and `/shots` remain explicitly restricted to WC 2022 and retain their M0
schemas, pagination, and exact 152/1,430 and 1,494-row contracts.
**Provider xG is deliberately not ingested** — it is the strongest leakage vector for the M2
shot-quality model. It is removed recursively before residual JSON is persisted and prohibited by a
database constraint.

Verification queries live in [`backend/sql/`](backend/sql/):

```bash
docker exec -i touchline-postgres psql -U touchline -d touchline -f - < backend/sql/wp0_3_reconciliation.sql
```

## Data quality and reconciliation (WP1.4)

After a successful scoped ingestion, run the independent read-only audit:

```bash
uv run poe quality
```

It reads source counts from the latest successful manifest for the exact pinned commit and scope,
then audits the already committed database in a separate read-only transaction. It never writes
source facts or manifests. It emits canonical JSON and text reports under `reports/`, separating
errors, warnings, reconciliation, invariant violations, coverage/missingness, deliberate exclusions,
and known limitations. The audit reconciles every persisted source grain for the chosen scope,
checks raw coordinate bounds (including the documented inclusive `location_x = 120.1`), two-team
match shape, typed-shot/event links, relation endpoints, and provider-xG absence in residual JSON.
It reports, rather than repairs, surprising source facts; in particular it does not infer position
chronology or minutes from lineup membership.

The report treats missing shot player, period, location, outcome, body part, technique, or shot
type as a zero-tolerance error: these are the explicitly declared eligibility/feature inputs for
the later model cohort. Generic-event and lineup missingness remain coverage observations with a
count, denominator, and basis-point rate; this project does not invent a completeness threshold for
them.

Category validation is scoped to observed source consistency: within the selected cohort, each
shot outcome/body-part/technique/type and event play-pattern/position ID must map to one name, and
each observed name to one ID. This is not a claim that the database validates an external provider
taxonomy. Non-null event actors without lineup membership are joined at the same match-team-player
grain; that warning is coverage evidence, never proof of an appearance or minutes played.

## SQL analysis pack (WP1.5)

Ten hand-written PostgreSQL queries live in [`backend/sql/wp1_5/`](backend/sql/wp1_5/). They cover
competition and match coverage, team results, home/away checks, descriptive shot prevalence,
player shot volume, event-type distribution and missingness, lineup participation evidence, and a
possession-scoped `LAG` sequence exercise. Each file documents its grain, join strategy, NULL
behaviour, and interpretation boundary.

The checked full-cohort results and two measured `EXPLAIN (ANALYZE, BUFFERS, SETTINGS)` plans are in
[`docs/analysis/wp1_5_sql_analysis_pack.md`](docs/analysis/wp1_5_sql_analysis_pack.md). A narrow
event-type index improved one manual aggregate but was rejected: it added about 5.6 MiB plus write
maintenance and served no recurring or production workload. No speculative secondary index was
retained.

## The baseline (WP0.4)

```
GET /baseline
```

Returns the observed conversion rate of the loaded cohort — currently **152 goals / 1,430
non-penalty shots = 10.63%** — together with the counts it came from and an explicit statement of
what it is not.

**It is a descriptive prevalence, not a model and not a prediction.** Nothing has been fitted, no
split was used, and no performance claim is made. It exists to prove the whole path (PostgreSQL →
query → API → UI) with something trivially correct.

**It is also not the baseline that M2 models are compared against.** That baseline is a different
object: estimated from the **training split alone**, then scored on validation and holdout rows
under the same log loss, Brier score and calibration protocol as every candidate model. A model
beats it on *those evaluation metrics*, not by being numerically distant from this prevalence.
Using this full-cohort rate as the prediction for holdout rows would be plain leakage — the rate is
computed from outcomes that include the holdout's own labels.

Three decisions worth knowing:

- **Penalties and shootout kicks are excluded**, per [ADR 0004](docs/adr/0004-cohort-scope-and-validation-design.md).
  Their geometry is nearly fixed, so a single rate covering both describes neither. Including the
  fixture's penalty goal would move the test rate from 1/3 to 2/4 — wrong, but still plausible
  looking, which is why the test asserts exact counts.
- **An empty database returns 503, not a rate of zero.** "Nothing has been ingested" and "nothing
  was scored" are different facts and must not produce the same answer.
- **Missing values are excluded explicitly rather than left to SQL's three-valued logic.** A NULL
  `shot_type` or `period` would drop a row silently; a NULL `outcome` would do worse — stay in the
  denominator while failing the goal filter, i.e. be counted as a definite miss on no information.
  The cohort requires all three to be known. WC 2022 has none missing, so no current count changes.

## The shot map (WP0.5)

```
GET /shots?limit=&offset=&match_id=
```

Read-only, and enforced as such — the query runs in a `READ ONLY` transaction rather than merely
being documented as safe. Responses are bounded and carry the unpaged total, so a client can tell
"these are all of them" from "these are the first page".

The page at `/` renders the result as a raw shot map: every recorded shot at its recorded location.
The encoding is deliberately restrictive while there is no evaluated model:

- **Every marker is the same size.** Size-by-value is how expected-goals maps encode a model
  output; using it here would imply a chance-quality estimate that does not exist.
- **No colour ramp, no heat map.** A continuous gradient reads as a probability surface. This is a
  scatter of things that happened.
- The only visual distinction is **goal versus non-goal**, which is the recorded outcome — a fact
  from the source, not an inference.

Shots with no recorded location are counted in the text rather than dropped, and a failed API call
says so explicitly instead of rendering an empty pitch that would read as "no shots were taken".

## Known gaps in M0

Stated rather than hidden — each is resolved by a later milestone or is a deliberate, recorded
trade-off.

- **No model.** The conversion rate is a description of the loaded data; M2 builds the model.
- CI builds and checks; it does not deploy. Railway and Vercel deploy from their own GitHub
  integrations — see [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).
- Neon's free tier suspends the compute after inactivity, so the first request after an idle period
  waits for it to wake.
- The repository can load the four-tournament cohort, but the live Neon database is not migrated or
  reloaded automatically; deployment remains a separate, verified operation.
- Neon operator commands intentionally do not support its pooled endpoint; migrations and ingestion
  must be run with the direct URL while the Railway API retains the pooled URL.
- Public row-level endpoints remain WC 2022-only until the publication gate in
  [`DATA_SOURCE.md`](DATA_SOURCE.md) is resolved.
- `npm audit` reports 3 high-severity advisories in transitive Next.js dependencies (`postcss`,
  `sharp`). The only offered fix downgrades Next.js by seven major versions, so it has not been
  applied. Re-check on the next Next.js release.
- No drift monitoring. A deliberate, recorded trade-off — see
  [ADR 0006](docs/adr/0006-deployment-approach.md).

## Data source and attribution

Data provided by **StatsBomb**. This project uses StatsBomb Open Data under its published terms;
the official README and Public Data User Agreement were reviewed on **2026-08-01**. The dated source
record, exact revision, coverage inventory, data dictionary, and unresolved publication questions
are in [`DATA_SOURCE.md`](DATA_SOURCE.md).

The official sources require both source attribution and the StatsBomb logo for published analysis.
Text attribution is present in the repository and deployed page, but the official Media Pack URL
currently redirects without exposing a clearly approved downloadable asset. Public row-level API use
also needs clarification under the agreement's data-redistribution restriction. Neither question is
silently treated as cleared; both are release gates recorded in `DATA_SOURCE.md`.

StatsBomb Open Data event data, StatsBomb 360 freeze frames, and continuous tracking data are three
different products. A freeze frame is a partial snapshot around an event, not continuous player
tracking, and nothing in this project describes it otherwise.

This project does not reproduce StatsBomb's proprietary xG model and makes no claim to.
