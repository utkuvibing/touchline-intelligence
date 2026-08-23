# Touchline Intelligence — contributor guidance

Touchline Intelligence is a deployed football analytics and applied-ML project built on a pinned
StatsBomb Open Data snapshot. Start with [`README.md`](README.md), then use
[`MODEL_CARD.md`](MODEL_CARD.md) for model methodology and [`DATA_SOURCE.md`](DATA_SOURCE.md) for
coverage, provenance and publication constraints.

## Current public state

- The FastAPI model API and Next.js model-evidence interface are deployed.
- The served release is `exp-20260810-wp2_8-release`.
- World Cup 2018 and Euro 2020 were used for development, World Cup 2022 for calibration, and
  Euro 2024 for the one-time tournament holdout.
- Historical row-level model predictions remain disabled pending written clarification of the
  StatsBomb/Hudl data-use terms.

## Non-negotiable data and modeling boundaries

- **Never ingest provider xG.** It is removed before typed storage and prohibited by a database
  constraint so it cannot become a model feature.
- **Do not rewrite source facts.** Missing optional values remain missing; malformed required
  structures raise; measured source exceptions stay explicit.
- **Use the correct football-data terms.** Event data, event-embedded shot freeze frames,
  StatsBomb 360 and continuous tracking are different products. This repository does not ingest
  StatsBomb 360 or tracking data.
- **Preserve evaluation history.** Euro 2024 was opened once as the historical model holdout. Do
  not retroactively tune the released model or calibration decision against it.
- **Do not overstate results.** The calibrated variant worsened Euro 2024 log loss and Brier score;
  that negative result is part of the public record.
- **Keep the publication gate closed** unless current written provider direction resolves the
  row-level redistribution question. Text attribution does not clear that question.
- **Preserve StatsBomb attribution** in the repository, deployed interface and published outputs.

## Working safely

- Inspect the relevant implementation and existing tests before changing behavior.
- Keep changes focused; do not rewrite historical reports, ADRs, artifacts or metrics to improve
  presentation.
- Treat migrations, leakage controls, source provenance, release artifacts, and publication gates
  as high-risk boundaries requiring explicit validation and independent review.
- Use training-fold-only preprocessing for any future model selection. Vocabulary construction,
  rare-level handling, scaling, encodings and spline fitting must not learn from validation rows.
- Keep training and serving feature computation in one versioned contract.
- Preserve unrelated working-tree changes and never point tests or write commands at a deployed
  database.
- Add tests for changed behavior and run the narrowest relevant validation first. Run broader
  acceptance only when the affected boundary warrants it.
- Report skipped checks and negative results honestly.

## Common commands

```bash
# Local PostgreSQL
docker compose -f infra/docker-compose.yml up -d

# Backend setup and service
uv sync --no-default-groups --group dev
uv run --no-sync poe migrate
uv run --no-sync poe ingest
uv run --no-sync poe api

# Complete backend validation, including modeling dependencies
uv sync
uv run poe check

# Frontend
npm --prefix frontend ci
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend test
npm --prefix frontend run build
```

Integration tests require a local PostgreSQL URL and create isolated schemas. Full-cohort tests
require a separate explicitly configured database containing the pinned four-tournament cohort;
they are not part of ordinary CI.

## Repository map

| Area | Location |
|---|---|
| API, ingestion and modeling | `backend/src/touchline/` |
| SQL analysis and verification | `backend/sql/` |
| Backend tests | `backend/tests/` |
| Next.js interface | `frontend/` |
| Local PostgreSQL | `infra/docker-compose.yml` |
| Source revision and hashes | `data/provenance/` |
| Model split artifacts | `data/model/` |
| Experiment artifacts | `experiments/` |
| Historical evidence | `reports/` and tracked files under `docs/` |

## Scope discipline

Prefer a small, defensible implementation over speculative infrastructure. Do not add new model
families, authentication, distributed systems, data providers or documentation layers without a
concrete requirement. Existing historical evidence is intentionally detailed; new work should not
copy that ceremony by default.
