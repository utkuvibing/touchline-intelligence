# Deployment (M0 WP0.6)

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
| `TOUCHLINE_DB_URL` | **yes** | `postgresql://user:pw@ep-xxx.eu-central-1.aws.neon.tech/touchline?sslmode=require` | Neon pooled connection string. There is no default — a missing value fails at startup rather than silently connecting nowhere. |
| `TOUCHLINE_CORS_ORIGINS` | **yes** in production | `https://touchline-intelligence.vercel.app` | Comma-separated. **No wildcard**: a `*` is dropped rather than honoured, so a stray asterisk fails closed instead of opening the API to every page on the internet. |
| `TOUCHLINE_ENVIRONMENT` | no | `production` | Surfaced by `/health` so it is obvious which instance is being inspected. |
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
2. Copy the **pooled** connection string. It ends in `?sslmode=require`; keep that.
3. Load the pinned World Cup 2022 snapshot **from your machine**, not from CI:

   ```bash
   TOUCHLINE_DB_URL='postgresql://...neon.tech/touchline?sslmode=require' uv run poe ingest --reset
   ```

   This reads the cached snapshot at the commit pinned in
   `backend/src/touchline/ingest/source.py`, reconciles source counts against the database inside
   the transaction, and commits only if they match. Expect
   **64 matches, 32 teams, 431 players, 1,494 shots**.

   `--reset` is destructive and is the supported way to re-run: the loader is not idempotent.

### 2. Railway (backend)

1. New project → Deploy from GitHub repo → this repository.
2. Railway reads `railway.json` and builds `Dockerfile` from the repository root. No start command
   is needed; the image has one.
3. Set `TOUCHLINE_DB_URL` and `TOUCHLINE_ENVIRONMENT=production`.
   Leave `TOUCHLINE_CORS_ORIGINS` for step 4 — the Vercel URL does not exist yet.
4. Generate a public domain (Settings → Networking → Generate Domain).
5. Confirm the deploy: `GET /health` should be `ok` and `GET /ready` should report
   `database: reachable`. If `/ready` says `degraded`, the database URL is wrong or Neon is
   unreachable — `/health` will still be `ok`, which is the distinction those two endpoints exist to
   make.

### 3. Vercel (frontend)

1. New project → import this repository.
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

This is a release check, not a CI job — CI has no deployment and no credentials. It asserts facts
rather than availability: that the database is reachable *from the API*, that `/baseline` returns
exactly 152/1,430 for the pinned snapshot, that `/shots` reports all 1,494, that the served HTML
actually contains shot markers, and that the page is not showing its API-error or
incomplete-tournament states.

Exit code 0 means every check passed. Record the run in the release notes.

## What is deliberately not here

- **No CD.** GitHub Actions builds and checks; it does not deploy. Railway and Vercel deploy from
  their own GitHub integrations. Wiring deploys through Actions would need platform tokens as
  repository secrets, and buys nothing at this size.
- **No connection pooling in the application.** A connection is opened per request. Neon's pooled
  endpoint handles the pooling; an application-side pool is M3 hardening with a measured need.
- **No drift or model monitoring.** There is no model. Structured request logging and health
  endpoints are the whole observability story, recorded as an accepted gap in ADR 0006.
- **No custom domain, no CDN configuration, no autoscaling.** Smallest paid/free plans, portfolio
  traffic.

## Failure modes worth recognising

| Symptom | Likely cause |
|---|---|
| `/health` ok, `/ready` degraded | `TOUCHLINE_DB_URL` wrong, or Neon asleep/unreachable. The API is alive; the database is not. |
| `/baseline` returns 503 with "no shots are loaded" | The database is reachable but empty — step 1's ingestion has not been run against it. |
| Page renders but says "Could not load shots from the API" | `NEXT_PUBLIC_API_BASE` is wrong, or the Railway service is down. |
| Page renders an empty pitch with no error | Should not happen: a failed fetch is stated explicitly. If it does, the API returned 200 with no rows. |
| Browser console shows a CORS error | `TOUCHLINE_CORS_ORIGINS` does not include the exact Vercel origin — scheme and host must match, and a preview URL is a different origin. |
| Map says "not the complete tournament" | Paging stopped early: the API returned fewer shots than its own reported total. |
