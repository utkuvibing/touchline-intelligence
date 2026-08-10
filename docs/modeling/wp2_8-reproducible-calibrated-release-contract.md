# WP2.8 - Reproducible Calibrated Model Release Contract

**Status:** implementation contract; the real acceptance/evidence run and independent review remain
required before WP2.8 is closed.

**Owner:** M2 shot-quality release. **Decision record:** [ADR 0014](../adr/0014-wp2-8-reproducible-calibrated-release.md).

## Scope and frozen inputs

WP2.8 assembles one separate, content-hashed release packet from the frozen WP2.4
`full_minus_presence` logistic artifact and the frozen WP2.7 Platt decision. It does not select or
refit a model, fit another calibrator, inspect WC2022 or Euro2024 again, change the API/UI, create a
second calibrated pickle, change `experiments/results.csv`, or add a new dependency or artifact
format. Serving remains M3.

Implementation starts from the merged WP2.7 `origin/main` commit
`f48a1032f88afab968562c3ba3600618a2ed580a`. A stale WP2.6 base is a STOP condition. The release
runner accepts descendants of that exact base only when `origin/main` still resolves to the
registered commit and the tracked worktree is clean.

## Portable persisted paths

Every path written to a config, manifest, experiment record, report reference, or release packet is
a canonical repository-relative POSIX path, such as
`experiments/shot_quality/exp-YYYYMMDD-wp2_8-release/`. The validator rejects Windows drive and UNC
paths, POSIX absolute paths, `~`, `..`, dot segments, backslashes, duplicate separators, and other
non-canonical spellings. Temporary checkout and staging paths exist only in process memory and are
never serialized.

## Authoritative WP2.7 chain

The release gate verifies the measured machine artifacts:

- `calibration-decision.json` and its decision digest, frozen-base identity, Platt-parameter
  digest, execution provenance, and registered config digest;
- `holdout-access-audit.json` and its one-open stage sequence, counts, membership digest, execution
  provenance digest, and measured evidence hashes;
- `holdout-metrics.json` and both raw/calibrated aggregate metric identities;
- `experiment-record.json`, its aggregate counts, decision/membership/provenance identities, and
  cross-referenced measured evidence hashes.

Evidence hashes for JSON machine artifacts are blocking. Reports, model cards, plots, and other
presentation-only references are retained as context but are not integrity-critical inputs; an
editorial change to one cannot invalidate the WP2.7 measured chain or the WP2.8 release manifest.

## Historical reproduction boundary

The real read-only database reproduction is a separate acceptance/evidence run. Ordinary
`uv run poe check` tests use controlled fixtures and cover orchestration, hashes, guards, failure
modes, comparison tolerance, and atomic publication only.

The acceptance runner creates a temporary checkout at the registered WP2.4 reproduction commit,
runs `uv sync --locked`, and invokes the registered WP2.4 command. It verifies that the historical
training entry point uses `load_development_cohort` and its `DevelopmentLeakError` guard. The
assignment lock is checked before the command starts. Only registered development match IDs may be
materialized; WC2022 and Euro2024 IDs are rejected before preprocessing and may never be loaded,
preprocessed, scored, or passed into the reproduction. The registered development anchors are
asserted separately: 2,872 shots, 115 matches, and fold sizes 570/552/602/576/572.

The exact-reproduction fingerprint records, explicitly:

- OS and architecture;
- Python implementation and version;
- uv version;
- `uv.lock` SHA-256;
- reproduction Git commit;
- reproduction config SHA-256.

Exact artifact and canonical JSON equality is claimed only when every registered fingerprint field
matches. A different environment uses the preregistered numeric tolerance and must not claim
byte-identical reproduction.

## Publication transaction

The packet is built in a temporary sibling staging directory. Every staged file and measured hash is
verified before publication. The final repository-relative packet path is checked for existence;
existing packets are never overwritten. Staging is then atomically renamed to the final path. Any
failure removes staging and publishes nothing.

The manifest records `release_status = "m2_qualified"`, `serving_status = "not_served"`,
`reproduction_scope = "development_only"`, and `new_holdout_access = false`. These fields are
release metadata, not an API/UI serving claim.
