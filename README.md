# Touchline Intelligence Platform

Football research and decision-support built on [StatsBomb Open Data](https://github.com/statsbomb/open-data)
— a validated relational dataset, a calibrated shot-quality model, and an analyst interface, with the
evidence trail that makes every number defensible.

> **Status: M0 (Walking Skeleton), in progress.**
> There is **no shot-quality model yet**, and **no performance claim anywhere in this repository has
> been evaluated**. M0 exists to prove one thing end to end — data → PostgreSQL → API → UI →
> deployment — and deliberately makes no modelling claims. See [`docs/PLAN.md`](docs/PLAN.md) for
> what each milestone adds.

## Documentation

| Document | What it covers |
|---|---|
| [`AGENTS.md`](AGENTS.md) | **Start here.** Current state, non-negotiable rules, and where each detail lives |
| [`docs/PLAN.md`](docs/PLAN.md) | Milestones, data scope, validation design, what must be defensible before a claim is used |
| [`docs/TARGETING.md`](docs/TARGETING.md) | Role fit tiers, employers, artifact↔requirement mapping |
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
| `uv run poe ingest --reset` | Load the World Cup 2022 slice (destructive reset) |
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
would fail if the behaviour broke. It has already caught two tests that passed for the wrong reason
and led to both being rewritten.

## Repository layout

```text
backend/src/touchline/   Python package — FastAPI, config, later: ingestion, features, modelling
backend/tests/           pytest
frontend/                Next.js + TypeScript, Vitest
infra/                   docker-compose for local PostgreSQL
scripts/                 documented developer entry points
docs/                    plan, targeting, ADRs, research, experiment rules
```

## Data ingestion (WP0.3)

```bash
uv run poe ingest --reset
```

Loads FIFA World Cup 2022 — 64 matches, 32 teams, 431 players, 1,494 shots.

**The source snapshot is pinned to a commit SHA, not `master`.** Open Data is a live repository, so
a load against `master` would drift and the measured counts in ADR 0004 would stop meaning anything.
Every load writes a provenance record — source commit plus a SHA-256 for each file read — to
[`data/provenance/`](data/provenance/), which is committed so another machine can prove it received
identical bytes. Downloaded files are cached under `data/statsbomb/<sha>/` (git-ignored);
`--offline` fails rather than downloading.

**The loader is not idempotent.** Every write is a plain `INSERT`, so a second run against a
populated database is refused with a message rather than silently duplicating rows. `--reset` drops
and recreates the tables, and is the supported way to re-run. Upserts, source-key conflict handling
and a run manifest are M1.

**The caller owns the transaction, and reconciliation happens before the commit.** The flow is
reset → load → read counts back → reconcile against the source → commit. Counts are read inside the
transaction, against rows that are written but not yet durable, so a mismatch rolls the whole load
back. Nothing in the loader module commits: committing first and reporting afterwards would make
reconciliation a description of data already kept.

**The WP0.3 schema is provisional and expected to be replaced in M1.** Five tables — `competitions`,
`teams`, `players`, `matches`, `shots` — with primary keys only: no foreign keys, no check
constraints, no indexes beyond the keys, no migration tool. Primary keys are present because they
make a duplicate load fail loudly; everything else is deferred to M1, where referential integrity
arrives together with the ingestion ordering and failure handling that make it enforceable.
See [`backend/src/touchline/ingest/schema.sql`](backend/src/touchline/ingest/schema.sql).

Only shots are stored. There is no full event model, no lineups and no possessions. One consequence
worth knowing before querying: **`players` is not a squad list.** A player appears only if they took
at least one shot, so WC 2022 yields 431 rows against roughly 830 players in the squads. Any
per-player denominator taken from this table would be wrong in a way that still looks plausible.
Complete squads arrive with lineups in M1.
**Provider xG is deliberately not ingested** — it is the strongest leakage vector for the M2
shot-quality model, and the cheapest guarantee that it never reaches a feature set is for it not to
be in the database.

Verification queries live in [`backend/sql/`](backend/sql/):

```bash
docker exec -i touchline-postgres psql -U touchline -d touchline -f - < backend/sql/wp0_3_reconciliation.sql
```

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

- No model and no shot map yet. The baseline above is a constant, not a model; the shot map is WP0.5.
- CI builds and checks; it does not deploy. Railway and Vercel deploy from their own GitHub
  integrations — see [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).
- Ingestion is not idempotent and the schema is provisional; both are M1 work (see above).
- Only one competition-season is loaded. The full four-tournament cohort in
  [ADR 0004](docs/adr/0004-cohort-scope-and-validation-design.md) arrives in M1.
- `npm audit` reports 3 high-severity advisories in transitive Next.js dependencies (`postcss`,
  `sharp`). The only offered fix downgrades Next.js by seven major versions, so it has not been
  applied. Re-check on the next Next.js release.
- No drift monitoring. A deliberate, recorded trade-off — see
  [ADR 0006](docs/adr/0006-deployment-approach.md).

## Data source and attribution

Data provided by **StatsBomb**. This project uses StatsBomb Open Data under its published terms;
the README and licence are re-reviewed before first ingestion and before every public release, with
the review date recorded in `docs/`.

StatsBomb Open Data event data, StatsBomb 360 freeze frames, and continuous tracking data are three
different products. A freeze frame is a partial snapshot around an event, not continuous player
tracking, and nothing in this project describes it otherwise.

This project does not reproduce StatsBomb's proprietary xG model and makes no claim to.
