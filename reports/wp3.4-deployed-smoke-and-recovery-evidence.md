# WP3.4 deployed smoke and recovery evidence

**Evidence date:** 2026-08-22

**Production main:** `146581822edd69401ea982485629030061f7f9da`

**Status:** **COMPLETE.** Step 5, WP3.4, and M3 closed after the deployed acceptance, recovery
transitions, isolated-resource lifecycle, and decommissioning-confirmed evidence received an
independent GPT-5.6 Sol review `PASS` on 2026-08-22.

## Scope and safety boundaries

This record covers the post-merge production smoke, isolated fresh-Neon rebuild, Railway
rollback/roll-forward, and Vercel Instant Rollback/Promote rehearsals required by WP3.4. Throughout
the rehearsals:

- the production database was never repointed to the isolated rebuild database;
- no production infrastructure was provisioned and no production secret, credential-bearing DSN,
  or sensitive variable value was printed or committed;
- no schema or data downgrade was attempted;
- the historical `/model/shots` publication gate remained closed; and
- provider xG remained outside the ingestion and serving contracts.

The isolated Neon endpoint is recorded only as a sanitized EU Central project/database identity;
connection credentials and complete DSNs are intentionally absent from this evidence.

## Production identity and deployed smoke

The native Railway and Vercel deployments triggered by the merge of PR #19 both served main
`146581822edd69401ea982485629030061f7f9da`. Phase A identity/readiness checks passed, including the
full `/ready` admission envelope. The production smoke then passed all 22 checks with process exit
code 0.

The same 22/22 smoke was rerun after every recovery transition below. It covered liveness,
readiness, pinned baseline and shot contracts, model identity and provenance, six golden
predictions, qualified metrics, the closed publication gate, request-ID behavior on successful and
error responses, allowed and rejected CORS behavior including preflight, and the deployed analyst
page.

## Phase C — isolated fresh-Neon rebuild

**Result: PASS; lifecycle cleanup: COMPLETE.** A brand-new isolated Neon database was
rebuilt without changing any production service binding. Its sanitized identity was:

- direct host/database:
  `ep-blue-frog-b2bh80g2.c-6.eu-central-1.aws.neon.tech/neondb`;
- pooled host/database:
  `ep-blue-frog-b2bh80g2-pooler.c-6.eu-central-1.aws.neon.tech/neondb`;
- region: EU Central.

No username, password, query parameters, connection string, or other credential is retained here.
The sanitized command forms executed were:

```powershell
$env:TOUCHLINE_MIGRATION_DB_URL='<redacted direct rehearsal DSN>'
uv run poe migrate

$env:TOUCHLINE_DB_URL='<redacted direct rehearsal DSN>'
$env:TOUCHLINE_ALLOW_REMOTE_WRITES='ep-blue-frog-b2bh80g2.c-6.eu-central-1.aws.neon.tech/neondb'
uv run poe ingest

docker build --tag touchline-wp34-phasec:146581822edd69401ea982485629030061f7f9da .
docker run --rm --publish <loopback-port>:8000 --env PORT=8000 `
  --env TOUCHLINE_DB_URL='<redacted pooled rehearsal DSN>' `
  touchline-wp34-phasec:146581822edd69401ea982485629030061f7f9da
```

The packaged image records OCI revision
`146581822edd69401ea982485629030061f7f9da`. Canonical ordered migrations therefore ran through the
direct/non-pooler DSN, ingestion used the explicit guard for that exact sanitized target, and the
packaged current backend ran through the pooled rehearsal DSN.

The rebuild produced the repository-pinned four-tournament counts:

| Relation / manifest count | Observed |
|---|---:|
| Matches | 230 |
| Teams | 54 |
| Players | 1,989 |
| Events | 843,050 |
| Lineups | 460 |
| Match-team memberships | 11,062 |
| Possessions | 39,262 |
| Event relations | 1,227,110 |
| Shots | 5,829 |
| Freeze-frame actors | 78,866 |

The Neon console showed approximately **844 MB** of storage after the rebuild. This is an observed
provider measurement, not a byte-exact repository acceptance threshold.

Packaged API checks against the isolated pooled runtime all passed:

| Check | Observed result |
|---|---|
| `/ready` | HTTP 200; `status=ready`, `database=reachable`, `database_schema=current`, `model_runtime=ready`, `model_version=exp-20260810-wp2_8-release`, `detail=null` |
| `/baseline` | 152 goals / 1,430 shots |
| `/shots` | total 1,494 public WC 2022 rows |
| `/model` | `exp-20260810-wp2_8-release` |
| `/model/shots` | HTTP 403 exact `publication_gate_closed` envelope |

After the checks and storage observation were recorded, the operator decommissioned the isolated
Neon rehearsal project on 2026-08-22 and supplied that confirmation for this closeout. Production
had never been repointed to it. No provider secret or credential-bearing DSN was retained, and no
further operation against the decommissioned resource was attempted.

## Phase D — Railway rollback and roll-forward

**Compatibility verdict: PASS.** The chosen prior release had already passed the full deployed
smoke. Between its commit and current main there was no change to `Dockerfile`, `railway.json`,
`backend/src`, `pyproject.toml`, or `uv.lock`; no migration was introduced. Its application and
recorded configuration contract were therefore compatible with the current forward-only schema
and production dependencies. Railway Rollback was treated as restoration of both the selected
image and its custom variables. No secret or sensitive variable value was copied into this record.

The non-secret operational inventory recorded for both target snapshots was:

| Variable/configuration | Sanitized effective identity |
|---|---|
| `TOUCHLINE_DB_URL` | Neon production database, pooled runtime path |
| `TOUCHLINE_MIGRATION_DB_URL` | Same Neon production database, direct migration path |
| `TOUCHLINE_CORS_ORIGINS` | `https://touchline-intelligence.vercel.app` |
| `TOUCHLINE_ENVIRONMENT` | `production` |
| `PORT` | Railway-injected listener port |

The redacted configuration fingerprint is the SHA-256 of the following newline-delimited canonical
identity (with no secret values):

```text
PORT=railway-injected
TOUCHLINE_CORS_ORIGINS=https://touchline-intelligence.vercel.app
TOUCHLINE_DB_URL=neon-production/pooled
TOUCHLINE_ENVIRONMENT=production
TOUCHLINE_MIGRATION_DB_URL=neon-production/direct
```

Both prior and current snapshots recorded fingerprint
`48e54991da719c731665fc1f8dadb2d27c25a119c41d60476f725613a389d773`. Effective dependency identity
was checked without revealing credentials: `/health` reported production, `/ready` proved the same
reachable/current database and ready model runtime, the pinned baseline/shot/model checks proved the
intended dataset and bundle, CORS admitted exactly the Vercel production origin, and the publication
gate remained closed.

| Role | Commit | Recorded deployment ID | Rehearsal activation ID |
|---|---|---|---|
| Prior known-good target | `c8c915ec5a8f3162551d90c48af35f32b411b3a0` | `b2eddd5a-95b9-46dc-a83c-4e02c884086c` | `da88e901-b488-4fe4-8c13-6a05421ac206` |
| Intended current target | `146581822edd69401ea982485629030061f7f9da` | `1889fd07-d0cb-4590-bf1b-793c89786549` | `75476c63-4c9d-45c4-b8f4-27e24c2c7c8f` |

Rollback to the exact prior target passed Railway health admission, the full `/ready` check, and
the full 22/22 deployed smoke. Roll-forward restored the exact intended current image/configuration
snapshot, `/ready` returned the full healthy envelope, and the full deployed smoke again passed
22/22 with exit code 0. No schema or data downgrade was performed.

## Phase E — Vercel Instant Rollback and Promote

**Compatibility verdict: PASS.** The current main changed only deployed-smoke validation and its
offline tests after the prior production frontend commit; frontend source and build inputs did not
change. The prior immutable frontend therefore retained the same public API base, expected backend
schema, production origin, and CORS contract as the current deployment. No environment variable was
changed for the rehearsal.

Both immutable builds recorded the same public build-time configuration:

| Vercel deployment | `NEXT_PUBLIC_API_BASE` | Backend identity during rehearsal |
|---|---|---|
| `YcQ3uXrG2jfKpt4x9g3gT5BahyLX` | `https://touchline-intelligence-production.up.railway.app` | Railway roll-forward activation `75476c63-4c9d-45c4-b8f4-27e24c2c7c8f`, restoring target `1889fd07-d0cb-4590-bf1b-793c89786549` at main `146581822edd69401ea982485629030061f7f9da` |
| `CoztUszygA5vtnMWDnAYnB9aJUjn` | `https://touchline-intelligence-production.up.railway.app` | Railway roll-forward activation `75476c63-4c9d-45c4-b8f4-27e24c2c7c8f`, restoring target `1889fd07-d0cb-4590-bf1b-793c89786549` at main `146581822edd69401ea982485629030061f7f9da` |

The API base is intentionally public. The full allowed-origin CORS and cross-endpoint smoke checks
passed through that identity under each frontend deployment.

| Role | Commit | Vercel deployment ID | Immutable deployment URL |
|---|---|---|---|
| Prior known-good production | `da44d55cf70bfb901e013ac205afbcbb80c8cf0c` | `YcQ3uXrG2jfKpt4x9g3gT5BahyLX` | `touchline-intelligence-gas9yw081-utku1551-7043-0c1a1fad.vercel.app` |
| Intended current WP3.4 production | `146581822edd69401ea982485629030061f7f9da` | `CoztUszygA5vtnMWDnAYnB9aJUjn` | `touchline-intelligence-3drnxzj8o-utku1551-7043-0c1a1fad.vercel.app` |

Vercel Instant Rollback repointed `touchline-intelligence.vercel.app` to the exact prior immutable
deployment. The provider overview showed rollback mode and the prior deployment as the production
target; the full deployed smoke passed 22/22. Promoting the exact intended current deployment undid
rollback mode and restored the production domain to deployment `CoztUszygA5vtnMWDnAYnB9aJUjn`.
The provider reported it `Ready`, sourced from main `1465818`; the final full smoke passed 22/22
with exit code 0.

## Final repository validation

Validation ran from the closeout tree based on production main. Both database variables pointed to
the loaded local four-tournament PostgreSQL database, so integration and full-cohort contracts did
not silently skip for lack of configuration.

| Check | Result |
|---|---|
| `uv run poe check` | PASS: Ruff format/check and mypy clean; 1,277 passed, 122 expected skips, 1 existing Starlette deprecation warning |
| `git diff --check` | PASS |
| PR #19 WP3.4 mutation delta on the merged implementation | 51 CAUGHT / 0 MISSED / 0 SKIP |
| PR #19 full mutation verification on the merged implementation | 361 CAUGHT / 0 MISSED / 0 SKIP |
| Final production deployed smoke | 22/22 PASS, exit code 0 |

This closeout changes evidence and current-status documentation only; it changes no runtime,
frontend, schema, migration, deployment configuration, or publication behavior. The mutation
results are the reviewed exact-implementation results from PR #19; no mutation contract changed in
this documentation-only closeout.

The independent reviewer found no remaining material issue after inspecting the operator-confirmed
decommissioning delta and authorized the Step 5, WP3.4, and M3 completion claim. Historical
row-level publication remains closed and is not cleared by this operational closeout.
