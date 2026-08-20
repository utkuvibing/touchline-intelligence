# Touchline Intelligence frontend

The frontend is the Next.js analyst interface for Touchline Intelligence. WP3.2 renders the frozen
WP3.1 model metadata, qualified calibration/holdout evidence, limitations, attribution, and a
publication-gated WC2022 historical workspace.

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
npm run build
```

## Current interface

The page fetches `/model`, `/model/metrics`, and `/model/shots` independently through the frozen
WP3.1 contract. It verifies the seven provenance identity fields before combining metadata,
metrics, and historical rows:

- `model_version`
- `release_id`
- `serving_manifest_sha256`
- `release_manifest_sha256`
- `release_manifest_file_sha256`
- `artifact_sha256`
- `calibration_decision_sha256`

Historical pages use the WP3.1 bound of 1,000 rows and page until the **returned** total is
satisfied. Offset stability inherits the pinned, unchanged database snapshot condition documented
by WP3.1. A duplicate, short, stalled, inconsistent, or provenance-mismatched page is shown as a
failure, never as an apparently empty or complete cohort.

The historical endpoint is expected to return `publication_gate_closed` in the public configuration.
The page still shows model identity, qualified metrics, reliability sample sizes, limitations, and
StatsBomb attribution. It does not substitute raw rows or issue hypothetical prediction calls to
reconstruct historical rows.

For controlled local historical acceptance only, set the backend variable
`TOUCHLINE_HISTORICAL_MODEL_SHOTS_ENABLED=true`. This does not clear the external StatsBomb/Hudl
publication question and must not be copied to production without written direction.

The historical map keeps StatsBomb coordinates and attacking direction. Probability is encoded by
marker area using the exact mapping:

```text
r(p) = sqrt(0.45² + p × (2.40² − 0.45²))
```

This makes circle area affine in probability. Goals are filled, non-goals are hollow, and a separate
outer ring marks selection; outcome does not depend on color alone. A single keyboard shot selector
provides accessible selection without putting every marker in the tab order.

The reliability view uses the adopted calibrated Euro2024 holdout variant, displays all returned bin
sample sizes and positive counts, and keeps the WC2022 calibration/adoption evidence separate. The
page does not call this model StatsBomb xG, does not make a causal recommendation, and does not
claim tracking or StatsBomb 360 coverage.

WP3.2 local implementation/acceptance, historical publication permission, and production
deployment/smoke are independent statuses. Production deployment and smoke evidence remain
WP3.3–WP3.4.
