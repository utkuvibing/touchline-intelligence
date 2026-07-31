# ADR 0001: Monorepo architecture

## Status

Accepted

## Context

One developer will build a Python/FastAPI backend, a Next.js/TypeScript frontend, data and modelling workflows, documentation, and local infrastructure over 8–9 months. The modules share a domain model, release story, and deployment path. Separate repositories would add coordination and versioning work without separate teams or independent scaling requirements.

## Decision

Use one Git repository. Keep the backend and frontend as clear top-level applications, with `docs`, `infra`, `experiments`, local `data`, and generated `artifacts` alongside them. Share contracts deliberately through documented API schemas; do not create generic shared packages until repeated code demonstrates a need.

The platform remains one deployable backend and one deployable frontend. Data ingestion and model training are commands within the backend codebase, not separate microservices.

## Alternatives considered

- **Separate repositories:** rejected because cross-cutting changes and portfolio onboarding would be harder for one developer.
- **Backend-only notebook repository:** rejected because it would not demonstrate product integration, API ownership, or TypeScript delivery.
- **Many internal packages/services from the start:** rejected because boundaries are not yet learned from real code.

## Consequences

- One clone and one documentation hierarchy make reproducibility and review easier.
- Backend, frontend, schema, model, and docs changes can be coordinated atomically.
- CI must use path-aware jobs eventually to stay fast.
- The repository can become noisy; ownership and generated-data rules must be explicit.
- Independent service scaling is deferred, which is acceptable for portfolio traffic and local research workloads.

## Review trigger

Review only if there are independent maintainers/release cycles, deployment coupling causes repeated failures, or a measured workload cannot be supported by the single backend. Repository size alone is not a trigger.

