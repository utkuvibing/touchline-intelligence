# Deployment (M0 WP0.6; hardening WP3.3, deployed smoke and recovery WP3.4)

```text
Vercel (Next.js)  ──HTTPS──►  Railway (FastAPI, Docker)  ──►  Neon (PostgreSQL)
```

Chosen for the reason in [ADR 0006](adr/0006-deployment-approach.md): the point is to have a real
containerised service with a real CI-built image and a real managed database, not to learn one
vendor's console. Nothing here is AWS-specific, and the concepts transfer.

## Cost — read before creating accounts

**This is not a wholly free stack.** Neon and Vercel are used on their free tiers. Railway is not.

| Service | Plan used | Cost |
|---|---|---|
| Neon | Free | no charge at this size |
| Vercel | Hobby (free, non-commercial) | no charge at this size |
| **Railway** | **Hobby** | **$5/month**, and adding the plan may require a payment card |

Railway's lower tiers are not a stable home for a service that should stay up:

- **Trial** — a one-time $5 credit, usable for up to 30 days. It runs out.
- **Free** — $1 of monthly resource credit. Enough to try a deploy, not enough to keep a
  container serving continuously for a month.
- **Hobby** — $5/month, the intended plan here. Actual usage for one small container is a fraction
  of that, but the subscription itself is the cost.

Verify current pricing on each provider's own page before committing — these change.

If a paid plan is not wanted, the backend can go to another container host instead; nothing in the
image or `railway.json` is Railway-specific beyond the healthcheck declaration, and the `PORT`
environment variable is the only platform contract the container relies on.

## Environment variables

### Railway — backend

| Variable | Required | Example | Notes |
|---|---|---|---|
| `TOUCHLINE_DB_URL` | **yes** | `postgresql://user:pw@ep-xxx-pooler.eu-central-1.aws.neon.tech/touchline?sslmode=require` | Neon **pooled** connection string for the serving API. There is no default — a missing value fails at startup rather than silently connecting nowhere. |
| `TOUCHLINE_MIGRATION_DB_URL` | **yes** | `postgresql://user:pw@ep-xxx.eu-central-1.aws.neon.tech/touchline?sslmode=require` | Neon **direct** connection string used only by Railway's pre-deploy migration command. Production must set it separately; it is not a runtime fallback. |
| `TOUCHLINE_CORS_ORIGINS` | **yes** in production | `https://touchline-intelligence.vercel.app` | Comma-separated. **No wildcard**: a `*` is dropped rather than honoured, so a stray asterisk fails closed instead of opening the API to every page on the internet. |
| `TOUCHLINE_ENVIRONMENT` | **yes** in production | `production` | Surfaced by `/health`. Set it explicitly: only a local/test label together with an actually local database may omit the dedicated migration URL; every remote runtime URL fails closed. |
| `PORT` | injected | — | Railway sets this; the container reads it. |

### Vercel — frontend

| Variable | Required | Example | Notes |
|---|---|---|---|
| `NEXT_PUBLIC_API_BASE` | **yes** | `https://touchline-api.up.railway.app` | No trailing slash. `NEXT_PUBLIC_` is correct here — the value is a public URL, not a secret. |

### Local

`.env.example` covers local development. Copy it to `.env`; it is git-ignored.

## Order of operations

The two URLs depend on each other — the backend needs the frontend's origin for CORS, and the
frontend needs the backend's URL — so one of them is configured twice. Neon first, because both
need it.

### 1. Neon (PostgreSQL)

1. Create a project, region close to the Railway region.
2. Copy both Neon connection strings. Use the **direct** hostname for
   `TOUCHLINE_MIGRATION_DB_URL` and operator migration/ingestion commands, and the `-pooler`
   hostname for Railway's `TOUCHLINE_DB_URL` serving API. Both end in `?sslmode=require`; keep that
   parameter. These are deliberately separate variables: pre-deploy migration execution is isolated
   from the web process, but Railway service variables may still be visible to the runtime container,
   so the application must never read or log the migration URL during serving.
3. Load the pinned four-tournament core cohort **from your machine**, not from CI. Ingestion writes
   application data, so it refuses any non-local target unless that exact database is named for the
   run — see "Writing to a non-local database" below:

   ```bash
   TOUCHLINE_ALLOW_REMOTE_WRITES='ep-xxx.eu-central-1.aws.neon.tech/touchline' \
   TOUCHLINE_DB_URL='postgresql://user:pw@ep-xxx.eu-central-1.aws.neon.tech/touchline?sslmode=require' uv run poe ingest
   ```

   The override value is the sanitized `host[:port]/database` the refusal prints. It carries no
   credentials, so it is safe in a runbook; the DSN beside it is not, and stays out of tracked files.

   This reads the cached snapshot at the commit pinned in
   `backend/src/touchline/ingest/source.py`, reconciles source counts against the database inside
   the transaction, and commits only if they match. Expect **230 matches, 54 teams, 1,989 players,
   843,050 events, 460 lineups, 11,062 lineup memberships, 39,262 possessions, 1,227,110 directed
   event relations, 5,829 typed shots, and 78,866 shot freeze-frame actors**.

   Normal reruns are idempotent and create their own manifest. `--reset` remains available only for
   an explicitly destructive local rebuild; it is not required for an identical rerun.

   For an existing populated database that must keep its rows, apply the non-destructive ordered
   schema upgrade first:

   ```bash
   TOUCHLINE_MIGRATION_DB_URL='postgresql://user:pw@ep-xxx.eu-central-1.aws.neon.tech/touchline?sslmode=require' uv run poe migrate
   ```

   **`poe migrate` needs no write-target override, and that is a decision rather than an oversight.**
   It was assessed separately from ingestion: it changes schema structure, not application data; it
   is a required step of this runbook, invoked deliberately with an explicit DSN; and `/ready`
   reports `database_schema: behind` precisely so an operator is *told* to run it. Extending the
   ingestion guard over it as a side effect would have broken this step without anyone deciding to.
   `backend/tests/test_write_target_policy.py` records the decision as an executable test, so
   changing it later fails a test and forces this section to be revisited with it.

   Both commands reject a known Neon `-pooler` hostname before opening a connection, taking a lock,
   writing a manifest, running a migration, or staging data. The error names the required direct
   URL but never prints the supplied DSN or credentials. This boundary exists because ingestion
   uses session-level advisory locks and temporary-table/data-transaction state that must remain on
   one PostgreSQL session.

   Migrations 0003–0005 preserve legacy shot rows by creating skeletal companion event rows;
   migrations 0006–0007 add the manifest lifecycle and measured raw event-x boundary. A subsequent
   normal `uv run poe ingest` fills the complete pinned source without rewriting identical facts.

   A Railway code deploy runs the packaged migration command through the `preDeployCommand` in
   `railway.json`, before the new container can pass its deployment healthcheck. It uses
   `TOUCHLINE_MIGRATION_DB_URL`; a non-zero migration exit blocks activation. This migrates schema
   only. Ingestion remains a separate, deliberate operator command and is never run by deploy.

   **This is a release-ordering obligation, not a note.** Any release whose queries reach a
   relation the deployed database does not have must apply the packaged migration successfully
   before the new container can pass `/ready`. Merging a migration and activating the code that
   depends on it are one ordered Railway release path; ingestion remains a separate operator
   action. The first row of *Failure modes worth recognising* describes the fail-closed response
   when that ordering does not complete.
   The internal database then holds four tournaments, while the current public `/baseline` and
   `/shots` endpoints remain explicitly restricted to WC 2022.

### Release prerequisite: protect `main` in GitHub

Before connecting either deployment provider, create and activate a GitHub ruleset (or equivalent
branch protection rule) targeting `main`. Require pull requests and require these CI status checks:

- `Backend (format, lint, types, tests)`
- `Frontend (lint, types, tests)`
- `Backend image builds`

The image check is a release prerequisite, not an optional build signal: it proves the production
Dockerfile builds, its entrypoint resolves, the serving bundle validates, and training-only Torch is
absent. Railway's **Wait for CI** setting is a second admission guard, but it does not replace a
durable repository rule preventing an unvalidated commit from landing on `main`. This repository
does not configure the GitHub-hosted rule itself; verify it is active in repository settings before
enabling either native Git deployment.

### 2. Railway (backend)

1. New project → Deploy from GitHub repo → this repository.
2. Railway reads `railway.json` and builds `Dockerfile` from the repository root. No start command
   is needed; the image has one.
3. Set `TOUCHLINE_DB_URL` to Neon's **pooled `-pooler` URL**, set
   `TOUCHLINE_MIGRATION_DB_URL` to Neon's **direct URL**, and set `TOUCHLINE_ENVIRONMENT=production`.
   Production must define both URLs; the pre-deploy command selects the migration URL while the
   running API selects the pooled URL.
   Leave `TOUCHLINE_CORS_ORIGINS` for step 4 — the Vercel URL does not exist yet.
4. Generate a public domain (Settings → Networking → Generate Domain).
5. Enable Railway's native GitHub integration with **Wait for CI**. Do not add a Railway token or a
   deploy job to GitHub Actions: Railway owns this native Git path and observes the protected
   branch's checks.
6. A backend release is complete only after all four gates are observed for the same commit:
   GitHub CI (including `Backend image builds`) succeeded; Railway's pre-deploy migration exited
   successfully; the new container started successfully; and its admission probe returned
   `GET /ready` with `status: ready`, `database: reachable`, `database_schema: current`, and
   `model_runtime: ready`. `GET /health` should remain `ok` as the separate liveness diagnostic.
   `/ready` reports
   three states, because there are three distinct things that go wrong:

   | `/ready` says | Meaning | Fix |
   |---|---|---|
   | `ready` / `reachable` / `current` | serving | — |
   | `degraded` / `unreachable` / `unknown` | the database is not answering | `TOUCHLINE_DB_URL` is wrong, or Neon is unreachable |
   | `degraded` / `reachable` / `behind` | PostgreSQL answers, but does not hold the relations this build queries | inspect the failed pre-deploy migration and correct `TOUCHLINE_MIGRATION_DB_URL` |

   `/health` stays `ok` in all three, which is the distinction those two endpoints exist to make.
   Railway uses `/ready` as a deployment admission gate while activating a release; it does not
   continuously monitor readiness after activation.

### 3. Vercel (frontend)

1. New project → import this repository through Vercel's native GitHub integration, targeting the
   protected `main` branch. Do not add a Vercel token or deploy job to GitHub Actions.
2. **Root Directory: `frontend`.** Without this the build has no `package.json` to find.
3. Framework preset: Next.js (detected).
4. Set `NEXT_PUBLIC_API_BASE` to the Railway URL from step 2.
5. Deploy, then copy the production URL.

### 4. Close the CORS loop

Back on Railway, set `TOUCHLINE_CORS_ORIGINS` to the Vercel production URL and redeploy.

Vercel also creates preview URLs per branch. If previews should work, add them as extra
comma-separated origins — they are separate origins and will otherwise be refused by the browser.

### 5. Smoke test the deployment

```bash
uv run python scripts/smoke_deployed.py --api https://<railway-url> --frontend https://<vercel-url>
```

This is a release check, not a CI job — CI has no deployment and no credentials. Since WP3.4 it
asserts the whole deployed contract rather than availability alone: the pinned WC 2022
descriptive facts (`/baseline` 152/1,430, `/shots` total 1,494); the full `/ready` admission
state (database reachable, schema current, model runtime ready, release label); X-Request-ID
correlation, including safe replacement of malformed IDs; the CORS allow-list from the outside;
the qualified release identity on `/model`; the golden fixture's provenance digests matching what
`/model` reports before `/model/predict` reproduces the frozen offline oracle's *public* outputs
within the tolerance the fixture itself declares; the qualified Euro 2024 holdout evidence on
`/model/metrics`; `/model/shots` answering exactly HTTP 403 `publication_gate_closed` with no
probabilities in the body; and the analyst page rendering the release, its scope counts, the
reliability view, the limitations, the StatsBomb attribution, and the publication-gate-closed
state without any error state.

Exit code 0 means every check passed. Record the run in the release notes.

## Rehearsing a rebuild on an isolated database

M3's acceptance requires an empty-database rebuild that is documented and has been performed
once. The rehearsal runs on its own Neon project/database. **The serving deployment is never
repointed**: production keeps its own databases and connection strings throughout, and the
rehearsal target is decommissioned afterwards.

1. Create a second Neon project (or a separate database in the same project). Copy its direct and
   pooled connection strings; they belong to this rehearsal only.
2. Apply the ordered migrations from your machine against the rehearsal **direct** URL via
   `uv run poe migrate` and `TOUCHLINE_MIGRATION_DB_URL`.
3. Ingest the pinned four-tournament cohort into it exactly as in step 1 of the order of
   operations, passing `TOUCHLINE_ALLOW_REMOTE_WRITES` naming the rehearsal host/database.
4. From your machine, run the packaged current image with its runtime variables pointed at the
   rehearsal pooled URL, then verify the pinned facts through it: `GET /ready` must report the
   full ready state, `/baseline` must return 152/1,430, `/shots` must report 1,494, and `/model`
   must name `exp-20260810-wp2_8-release`.
5. Record the commands, counts, and readiness bodies as rebuild evidence, then decommission the
   rehearsal database in the provider console.

This is the production-target form of the clean-build proof WP1.6 established locally; the data
is reproducible from the pinned source, which is precisely why wiping nothing and risking nothing
is the right rehearsal shape.

## Rolling back a backend release

Rollback never downgrades the schema or data. Migrations are forward-only, and no schema/data
downgrade is performed during an application rollback. An application rollback is allowed only
after the chosen prior release has been explicitly verified compatible with the currently deployed
schema and data. The expand-compatible migration policy reduces rollback risk; it does not prove
that an arbitrary older image remains compatible forever. If compatibility cannot be established,
do not roll back the application: keep the current deployment admitted and forward-fix instead.

Railway's [**Rollback** action](https://docs.railway.com/deployments/deployment-actions#rollback)
restores the selected successful deployment's Docker image **and its custom variables**. It is
therefore not an application-code-only operation. [**Redeploy**](https://docs.railway.com/deployments/deployment-actions#redeploy)
is a different action: it creates a new deployment from the selected deployment's same code and
build/deploy configuration. Choose the action deliberately, and account for the selected
deployment's configuration before activation.

Record before touching anything:

- the exact prior release commit SHA and its Railway deployment ID;
- the exact current release commit SHA and its Railway deployment ID;
- a non-secret identity/inventory of the operational variables and configuration required by the
  current service and carried by the candidate prior deployment (variable names, referenced
  resource identities, and a redacted configuration fingerprint are sufficient; never print or
  persist secret values);
- the observed `GET /ready` body of the healthy current deployment.

Then rehearse, in order:

1. Before selecting a target, verify that the prior application is compatible with the current
   production schema/data and that the target deployment's restored custom variables reference the
   intended current production dependencies. If either cannot be established, stop and forward-fix.
2. Use Railway **Rollback** on the verified prior deployment, acknowledging that this restores both
   its Docker image and its custom variables. Do not copy secret values into the rehearsal evidence.
3. Wait for healthcheck admission, confirm `GET /ready` reports the full ready state, and verify the
   required configuration behavior and dependency identities through non-secret operational checks.
4. Roll forward by restoring or activating the exact intended current deployment **and** its
   intended current configuration recorded above. Do not use **Redeploy** as though it were
   synonymous with **Rollback**.
5. Rerun the full deployed smoke from section 5 and record N/N checks alongside the commit SHAs,
   deployment IDs, and redacted configuration identities. Do not expose secrets in evidence.

Vercel's instant rollback redeploys a prior build; the frontend has no schema, so the redeploy is
the entire procedure there. The first backend rollback rehearsal is part of the WP3.4 evidence.

## Writing to a non-local database

`poe ingest` is the only repository command that mutates application data, and it fails closed:
unless `TOUCHLINE_DB_URL` resolves to a local PostgreSQL, it refuses before opening a connection,
opening the source snapshot, taking a lock or writing a manifest.

| Target | Default | How to proceed deliberately |
|---|---|---|
| `localhost`, any loopback address, `*.localhost` | allowed | — |
| Neon, staging, any other remote host | **refused** | `TOUCHLINE_ALLOW_REMOTE_WRITES='<host[:port]/database>'` for that one command |
| Unclassifiable or malformed DSN | **refused** | fix the DSN |

The override must equal the sanitized target exactly — the same `host[:port]/database` string the
refusal prints. A generic `1` or `true` is rejected: such a value can be left exported from an
unrelated experiment and would then disarm the guard for every later command, whereas a value
naming one specific database cannot be reused by accident against a different one. Supply it inline
per command; do not export it into a shell profile or a platform variable.

Staging and production follow the same rule. A production-only deny-list would need maintaining,
and the run that hurts is the one against a host nobody remembered to add to it.

Classification is derived from the DSN and **never** from `TOUCHLINE_ENVIRONMENT`. That variable is
free-text, exists to label `/health` output, and can read `local` in front of a deployment DSN — in
this repository it has. A safety control that trusted it would fail at exactly the moment the label
is the thing that is wrong.

The refusal names only `host[:port]/database`. Username, password and query parameters — where Neon
puts its credentials and endpoint tokens — are never read into the message, so the guard cannot leak
a DSN into a terminal, a CI log or a pasted bug report.

**Not covered, deliberately:** `poe migrate` (see step 1), every read-only command (`poe quality`,
the SQL analysis packs, `scripts/smoke_deployed.py`), and direct programmatic use of
`touchline.ingest` internals by the test suite, which runs against whatever database the test
environment provides.

## What is deliberately not here

- **No token-driven CD workflow.** GitHub Actions builds and checks; it does not deploy. Railway and
  Vercel deploy from their native GitHub integrations after the protected branch checks pass.
- **No connection pooling in the application.** A connection is opened per request. Neon's pooled
  endpoint handles the pooling; an application-side pool is M3 hardening with a measured need.
- **Operator and pre-deploy migrations require Neon's direct endpoint.** `poe migrate` and
  Railway's `preDeployCommand` use `TOUCHLINE_MIGRATION_DB_URL`; ingestion receives a direct URL as
  its operator-scoped `TOUCHLINE_DB_URL`. All reject the `-pooler` hostname before database work,
  while Railway's normal API requests retain the pooled runtime URL.
- **No environment-name allow-list.** The write-target guard classifies from the DSN host alone. A
  list of "safe" environment names is a second source of truth that drifts from the DSN it is meant
  to describe, and it drifts silently.
- **No drift or model monitoring.** The qualified calibrated model is served, but automated model
  drift and performance monitoring are not implemented. Structured request logging, health and
  readiness endpoints, immutable model provenance, and pinned evaluation evidence are the current
  observability boundary; the monitoring gap remains recorded in ADR 0006.
- **No custom domain, no CDN configuration, no autoscaling.** Smallest paid/free plans, portfolio
  traffic.

## Failure modes worth recognising

| Symptom | Likely cause |
|---|---|
| Railway rejects a release and `/ready` reports `database_schema: behind` | The pre-deploy migration failed or did not bring the schema to the revision required by this build. Inspect Railway's `preDeployCommand` log, correct `TOUCHLINE_MIGRATION_DB_URL` or the migration defect, and redeploy. The failed migration or schema-behind readiness state blocks admission; do not bypass it with a manual code activation. |
| `/health` ok, `/ready` degraded | `TOUCHLINE_DB_URL` wrong, or Neon asleep/unreachable. The API is alive; the database is not. |
| `/baseline` returns 503 with "no shots are loaded" | The database is reachable but empty — step 1's ingestion has not been run against it. |
| `poe migrate`, `poe ingest`, or pre-deploy migration rejects `-pooler` | A migration path was given Railway's pooled API URL. Set `TOUCHLINE_MIGRATION_DB_URL` to Neon's direct URL; keep the Railway runtime `TOUCHLINE_DB_URL` pooled. |
| Page renders an error notice such as "Model metadata unavailable" | `NEXT_PUBLIC_API_BASE` is wrong, or the Railway service is down. The analyst view states every failed fetch explicitly and withholds the affected section rather than rendering a partial model view. |
| Page says "Model identities do not agree" | `/model` and `/model/metrics` reported different provenance — possible only if two releases are mixed across simultaneous deploys. Redeploy so both endpoints come from one image; the view withholds metrics and historical rows until identities agree. |
| Browser console shows a CORS error | `TOUCHLINE_CORS_ORIGINS` does not include the exact Vercel origin — scheme and host must match, and a preview URL is a different origin. |
| Page shows "Historical shot map is not publicly enabled" | Expected, not a failure: `/model/shots` answered `publication_gate_closed`, and the interface renders that state deliberately while the publication gate is open at DATA_SOURCE.md. |
