# WP2.7 holdout metrics schema clarification

This is a presentation-only clarification; `holdout-metrics.json` and the completed audit are
immutable and are not rewritten.

The schema-version-1 top-level field `raw_anchor_reliability` is copied by
`evaluate_holdout_rows` from the frozen calibration decision's `raw_anchor_reliability` field. It
is therefore WC2022 calibration adoption provenance. Its five counts total 1,430, not the 1,304
Euro2024 holdout rows.

For downstream interpretation, read that legacy field as:

```text
calibration_raw_anchor_reliability
```

The Euro2024 reliability tables are the `reliability` arrays nested under
`variants.raw` and `variants.calibrated`. Those variant records each have `n = 1304` and contain
the actual holdout reliability aggregates.

This distinction is semantic labeling only. It does not alter the measured metrics, decision,
membership digest, audit ledger, or evidence hashes.

Data provided by StatsBomb.
