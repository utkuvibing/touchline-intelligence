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
| [`docs/PLAN.md`](docs/PLAN.md) | Milestones, data scope, validation design, what must be defensible before a claim is used |
| [`docs/TARGETING.md`](docs/TARGETING.md) | Role fit tiers, employers, artifact↔requirement mapping |
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
| `uv run poe api` | Run the API at http://localhost:8000 |
| `uv run python scripts/verify_tests_fail.py` | Break each protected behaviour once and confirm the tests catch it |
| `cd frontend && npm run dev` | Next.js dev server |
| `cd frontend && npm test` | Vitest |
| `cd frontend && npm run typecheck` | tsc |
| `cd frontend && npm run lint` | ESLint |

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

## Known gaps in M0

Stated rather than hidden — each is resolved by a later milestone or is a deliberate, recorded
trade-off.

- No ingestion, no model, no shot map yet — WP0.3 through WP0.5.
- CI is written but has not run yet; the first push to GitHub is its first verification.
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
