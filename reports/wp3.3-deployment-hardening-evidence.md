# WP3.3 deployment hardening evidence update

**Status:** local acceptance evidence updated; production activation and WP3.3 completion remain **OPEN**.

**Branch:** `codex/wp3-3-railway-hardening`

**Scope:** This record covers the two WP3.3 blocker repairs and their local acceptance checks. It
does not claim a Railway/Vercel deployment, production migration, deployed smoke, rollback, or any
WP3.4 evidence.

## Environment

The checks below ran from the repository shell against the local development database only:

| Dependency | Observed state |
|---|---|
| Docker | Client and server healthy; Docker context `desktop-linux` |
| PostgreSQL container | `touchline-postgres` running and healthy |
| PostgreSQL endpoint | `localhost:5433` |
| Runtime image | `touchline-api:wp3-1-acceptance` built and probed |

No production or managed-host endpoint was used.

## Executed checks

| Check | Result |
|---|---|
| `uv run pytest backend/tests/test_migrations_integration.py::test_concurrent_migration_attempts_are_serialized_by_the_advisory_lock -q` | PASS |
| `uv run pytest backend/tests/test_migrations_integration.py -q` | PASS; 44 tests |
| Focused WP3.3 suite with `TOUCHLINE_DB_URL=postgresql://touchline:localdev@localhost:5433/touchline` | PASS; 136 tests |
| `uv run poe wp3-1-docker-acceptance` | PASS; image build, runtime probe, missing/corrupt/unsupported bundle probes |
| Packaged `python -c "from touchline.main import app"` with malformed migration URL and local runtime URL | PASS; serving import succeeded |
| Packaged `python -m touchline.ingest.migrate` against local PostgreSQL via `host.docker.internal:5433` | PASS; schema current |
| Selected WP3.3 mutation contracts | PASS; 9 CAUGHT, 0 MISSED |
| `uv run poe check` | PASS; 972 passed, 304 skipped, 1 warning |
| `git diff --check` | PASS (CRLF-aware check; no working-tree diff) |

The focused suite includes successful and rejected CORS `OPTIONS` preflights, request-ID
propagation, exactly one completion record, generic 500 CORS behavior, migration-only runtime
configuration isolation, direct migration URL selection, local/test fallback restrictions, and
pooled Neon rejection.

## Remaining gates

- Railway native GitHub integration, Wait for CI, production variables, pre-deploy migration, and
  `/ready` deployment admission have not been exercised against production.
- Vercel production Git flow has not been changed or smoke-tested here.
- WP3.4 browser smoke, clean rebuild rehearsal, and rollback rehearsal remain out of scope.

The local concurrency and packaged-runtime evidence is now complete for this acceptance slice, but
these remaining external and WP3.4 gates keep WP3.3 **OPEN**.
