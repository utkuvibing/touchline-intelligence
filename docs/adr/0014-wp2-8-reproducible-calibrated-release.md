# ADR 0014: WP2.8 reproducible calibrated-model release

**Status:** accepted as the WP2.8 implementation decision; real-data acceptance and the independent
WP2.8 review remain open.

**Date:** 2026-08-10

## Context

WP2.7 produced the one-time calibration and holdout evidence for the already-selected WP2.4
logistic artifact. M2 needs a defensible release boundary without turning reports into executable
inputs, rerunning supervised analysis, or implying that serving exists. A historical training
reproduction is valuable evidence, but it is expensive and must not become an ordinary test-suite
side effect.

## Decision

Use a separate `experiments/run-configs/wp2_8-release.json` registration and
`touchline.modeling.wp2_8` runner. The official command is `uv run poe wp2-8-release`.

The runner verifies the exact merged WP2.7 base, clean tracked state, the frozen WP2.4 artifact and
manifest, and the WP2.7 measured JSON chain. Only machine evidence is integrity-critical;
presentation files are references. All persisted paths are canonical repository-relative POSIX
paths.

The historical reproduction runs outside `poe check` in a temporary checkout at the registered
WP2.4 commit. Its loader and row guard admit development rows only. WC2022 and Euro2024 are
explicitly forbidden. Exact equality is recorded only for the fully matching environment fingerprint
(OS/architecture, Python implementation/version, uv version, lock SHA, reproduction commit, and
config SHA); other environments use the registered numeric tolerance without a byte-identity claim.

The packet is staged beside its final repository-relative destination, verified, and atomically
renamed. An existing packet is a hard failure. The manifest is content-hashed and records
`release_status = "m2_qualified"` and `serving_status = "not_served"`.

## Consequences

The release can be reviewed and moved without touching `experiments/results.csv` or creating a
second calibrated model artifact. Editorial report changes cannot invalidate measured WP2.7
identity. The acceptance run still requires the registered read-only database and a clean
historical checkout, so ordinary unit/integration validation cannot prove the final full-cohort
reproduction. M3 remains responsible for API/UI serving.
