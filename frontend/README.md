# Touchline Intelligence frontend

The frontend is the Next.js interface for Touchline Intelligence. In M0 it renders the recorded
FIFA World Cup 2022 shots returned by the FastAPI backend and the cohort's descriptive conversion
rate. It does not display a trained model, shot-quality predictions, or evaluated performance.

## Runtime and setup

Node.js is pinned in [`../.nvmrc`](../.nvmrc), and npm dependencies are locked in
[`package-lock.json`](package-lock.json).

```bash
npm ci
npm run dev
```

The development server runs at <http://localhost:3000>. The backend must be available separately;
see the [root README](../README.md) for complete local setup.

`NEXT_PUBLIC_API_BASE` selects the FastAPI base URL. It defaults to
`http://127.0.0.1:8000` for local development and is required in the deployed Vercel environment.
It is a public service URL, not a secret.

## Checks

```bash
npm run lint
npm run typecheck
npm test
```

`npm test` runs the Vitest suite once. `npm run test:watch` is also available for local iteration.

## Current architecture and limits

The root page is a dynamically rendered async Server Component. It fetches the bounded `/shots`
endpoint page by page and fetches `/baseline` without caching, then passes the results to synchronous
tested components. The map shows recorded locations and outcomes only: marker size is fixed, and no
probability field or colour scale is present.

The current UI covers one tournament and has no filters, shot-detail panel, calibration view, or
model output. Those capabilities belong to later milestones; [`../docs/PLAN.md`](../docs/PLAN.md) is
the authoritative plan. Start with [`../AGENTS.md`](../AGENTS.md) for current project state and
non-negotiable rules, [`../DATA_SOURCE.md`](../DATA_SOURCE.md) for source coverage and publication
conditions, and [`../docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md) for deployment details.
