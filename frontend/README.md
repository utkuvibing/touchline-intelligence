# Touchline Intelligence frontend

The Next.js interface presents the served model's identity, tournament-holdout results,
calibration evidence, limitations and data attribution. It treats the historical shot-level
workspace as a separate capability because its public availability depends on the unresolved
StatsBomb/Hudl data-use question.

## Run locally

Node.js is pinned in [`../.nvmrc`](../.nvmrc), and npm dependencies are locked in
[`package-lock.json`](package-lock.json).

```bash
npm ci
npm run dev
```

The development server runs at <http://localhost:3000>. The backend must be available separately;
see the [root README](../README.md) for complete setup.

`NEXT_PUBLIC_API_BASE` selects the FastAPI base URL. It defaults to
`http://127.0.0.1:8000` during local development and is required for production builds. It is a
public service URL, not a secret.

## Checks

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

## Interface boundaries

- Model metadata and metrics must carry the same release provenance before they are combined.
- Historical pages fail visibly on incomplete, duplicate, stalled or inconsistent pagination.
- A closed publication response produces a plain-language data-use boundary; the UI does not
  reconstruct historical rows through hypothetical predictions.
- Probability is encoded by marker area, while outcome also has a non-colour encoding.
- Reliability bins retain their sample sizes so sparse evidence remains visible.
- The page does not call this model StatsBomb xG and does not describe event freeze frames as
  tracking data or StatsBomb 360.

For controlled local acceptance only,
`TOUCHLINE_HISTORICAL_MODEL_SHOTS_ENABLED=true` may enable the historical endpoint. This does not
clear the external publication question and must not be copied to production without written
direction.
