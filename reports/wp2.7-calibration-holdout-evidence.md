# WP2.7 calibration and holdout evidence

**Status:** pre-registered, not executed.

This contract/implementation pass accessed no WC2022 or Euro2024 rows or labels. Consequently this
file contains no calibration parameters, holdout metrics, prevalence result, slice result, bootstrap
interval, or evidence claim.

The implementation is locked to the registered WP2.7 configs and externally pinned WP2.4 artifact
and manifest. Calibration decisions preserve exact Platt floats and current clean code/config/lock
provenance; no real phase exposes artifact or bootstrap overrides.

The real evidence packet is produced only by the two declared supervised phases:

1. `uv run poe wp2-7-calibrate` writes the immutable `calibration-decision.json` after opening
   WC2022 only.
2. `uv run poe wp2-7-holdout` opens Euro2024 once and writes `holdout-metrics.json`,
   `holdout-access-audit.json`, `evidence.md`, `model-card.md`, and the two plots in the same
   execution.

The final packet will contain only selected-logistic raw and calibrated variants. The constant
baseline is excluded; observed prevalence is descriptive context only. Later automated checks must
remain metadata-only or synthetic and must not reload Euro2024 rows or labels.
The final audit reconciles rows, matches, goals, and misses; hashes each evidence file separately;
and records `holdout_closed` only after the database connection closes.
