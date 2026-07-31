# ADR 0006: Deployment approach — Docker, GitHub Actions, one managed host

## Status

Accepted — 2026-07-31

## Context

Cloud platforms appear as essential in 8 of 30 scanned postings and desirable in 5 more; CI/CD in 3
essential and 2 desirable; Docker in 2 and 2. The wording is consistently about operating software
rather than naming a vendor — *"deployed, monitored and trusted in live environments"*,
*"Practical experience with CI/CD pipelines (Azure DevOps or GitHub Actions)"*,
*"Familiarity with containerisation (Docker) and orchestration tools"*. Named providers are split
across AWS, Azure and GCP, so no single one dominates.

The original plan deployed once, late, bundled into the same work package as PDF generation. For a
developer with no prior deployment experience that estimate was unrealistic, and the sequencing was
worse: an API and UI would be built for months without ever having run anywhere but localhost, so
every environment assumption would surface at once, at the end.

## Decision

**Docker + GitHub Actions + one simple managed deployment target.** No AWS or Azure in the core
roadmap.

- **First deploy happens in M0**, while the project is a handful of files. The pain is paid early and
  incrementally rather than all at once at the end.
- GitHub Actions from M0: install from lockfiles, lint, type check, test. A build→deploy chain is
  added in M3.
- Docker for both local PostgreSQL and the application image.
- Observability is deliberately shallow: structured logs, request IDs, health and readiness
  endpoints. **No drift monitoring** — an accepted, stated gap.
- M3 hardens what M0 established: migrations on boot, secret handling, smoke tests against the
  deployed instance, documented rebuild and rollback.

A cloud provider may be added later **only** via a further ADR that names a concrete learning or
targeting benefit.

## Alternatives considered

- **AWS (SageMaker, ECS) in the core:** rejected — high setup cost and vendor-specific surface for a
  developer who has not yet deployed anything. It would consume the milestone that produces the
  interface, which the same evidence shows is the profile's strongest differentiator.
- **Deploy once at the end (original plan):** rejected — concentrates all environment risk at the
  worst moment and leaves nothing publicly visible for months.
- **No containerisation, PaaS git-push only:** rejected — Docker is named directly in postings, and
  without an image the CI story is thin.
- **Add orchestration (Airflow/Dagster) and a warehouse:** rejected — see ADR 0007.

## Consequences

- Real, demonstrable competence in containerisation, CI/CD, migrations and health checking; no
  vendor-console experience.
- Postings that hard-require a named cloud platform are a partial match. The prepared answer is that
  provider specifics are a configuration layer over the same concepts, deliberately deferred rather
  than half-learned.
- Deploying in M0 means the earliest deployment is of a deliberately minimal system. The README must
  say so.
- Docker must be installed locally. It was not present on the development machine at the time of this
  decision and is a setup prerequisite for M0 WP0.1.

## Review trigger

A target role hard-requires a specific cloud platform and reaches final stages; deployment costs
exceed the managed host's free tier; or the application outgrows a single service.
