# M5 WP5.3 — Production hardening

**Status:** complete. **Source of truth:** `docs/PLAN.md` M5 work items 7–8. Historical v1
evidence and packets remain immutable.

## Work packages and acceptance criteria

1. **Dependency and release-packet debt.** Upgrade the frontend lock to remove every high or
   critical advisory; audit the locked Python environment. The frozen v1 `notes.md` presentation
   digest remains deliberately excluded from `verify_release_manifest` authoritative verification:
   its registered role is `presentation`, not measured release input. Do not rewrite the packet.
   **Accept when:** both audits report zero high/critical findings and the existing regression
   contract still proves editorial-note changes do not invalidate authoritative verification.

2. **Bounded runtime database access.** Create one lifecycle `psycopg_pool.ConnectionPool`, use it
   for `/ready`, `/baseline`, `/shots`, and `/model/shots`, and close it on shutdown. Configure
   typed min/max/timeout settings. **Accept when:** every runtime route borrows only from that
   application-owned pool, lifecycle cleanup covers normal shutdown and failed startup, constructor
   tests pin the configured maximum, and no request can borrow above that maximum.

3. **Readiness probe coalescing.** Use a short monotonic TTL and true concurrent single-flight,
   not merely a cache: one expired miss performs one database check and all callers already waiting
   on that flight receive the same result, including a failure. Evaluate model-runtime state afresh
   for every response. **Accept when:** concurrency tests prove exactly one underlying operation for
   simultaneous misses, both success and failure results are cached for the bounded TTL, and the
   public result exposes only registered operational detail codes.

4. **Public API hardening and diagnostics.** Permit only `Content-Type` and `X-Request-ID` CORS
   request headers, disable API docs/OpenAPI outside local/test, keep generic public 500s, and emit
   a separate structured `unhandled_exception` record with request ID, error type, and bounded
   sanitized frame identities only. **Accept when:** logs contain no exception message, locals,
   request data, headers, DSNs, feature rows, or uploads; public 503s contain no driver/schema or
   remediation detail; CORS/docs contracts are tested.

5. **API-driven frontend state.** Derive serving/publication badges and copy from those typed
   operational values, correct stale milestone wording without touching historical evidence, and
   add an accessible Next.js error boundary with retry. Preserve immutable M2 fields separately
   from current operational state. **Accept when:** the backend schema and frontend parser admit
   only the registered serving/publication literals, parser tests reject unregistered states, and
   rendering/failure-state tests prove the UI cannot display hard-coded contradictory status.

6. **Focused browser smoke with final-HEAD evidence.** Keep one Playwright spec for page load,
   valid prediction, structured invalid 422, and closed publication gate. URLs come from
   environment variables. **Accept when:** the smoke refuses to run unless
   `TOUCHLINE_SMOKE_EXPECTED_HEAD` equals the checked-out final `git rev-parse HEAD`, and attaches
   both SHAs and target URLs to its report before browser assertions; prediction, validation and
   publication-gate calls execute through browser-context `fetch`, and release evidence therefore
   cannot be reused for an earlier commit.

7. **Validation and delivery.** Run focused tests first, then backend checks, frontend lint/type
   checks/tests/build, audits, Docker build, smoke, diff review, and independent Sol review.
   **Accept when:** the final review is PASS and every skipped check is recorded honestly.
