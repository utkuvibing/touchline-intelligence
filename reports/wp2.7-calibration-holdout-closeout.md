# WP2.7 calibration and one-time holdout - closeout

This is a presentation-only closeout derived from the immutable WP2.7 calibration decision,
holdout metrics, audit manifest, and experiment record produced by the completed supervised run.
The measured JSON artifacts and their recorded evidence hashes are not rewritten.

## Audit and decision of record

- Calibration decision SHA-256: `f5c9ccf665924069f755fbd669d4a9abada1e5791e957d3d436d42d500277e89`
- Holdout aggregate: 1,304 rows, 51 matches, 98 goals, 1,206 misses
- `holdout_open_count`: `1`
- Ordered ledger: `holdout_open`, `membership_asserted`, `scored`, `bootstrap`, `slices`,
  `evidence_written`, `holdout_closed`, `experiment_record_written`, `audit_finalized`
- Pre-holdout adopted variant: `calibrated`

The adopted calibrated variant remains the decision of record. Euro2024 was used only for the
predeclared final comparison; it did not reselect raw versus calibrated.

## Calibration adoption rule

The WC2022 decision used raw-anchor five equal-width bins, D11 support of 100, and the registered
`wp2.7-calibration-adoption-v1` rule. All conditions passed:

| Condition | Immutable decision evidence | Result |
|---|---:|---|
| Platt slope finite and positive | slope `1.256307409023587` | PASS |
| At least one supported raw-anchor bin | `supported_bins = 1` | PASS |
| Calibrated maximum supported deviation improves | `0.004302015683` vs raw `0.012247769394` | PASS |
| Calibrated log loss does not worsen beyond `1e-12` | `0.283935933001` vs raw `0.287490481491` | PASS |
| Calibrated Brier does not worsen beyond `1e-12` | `0.082042526407` vs raw `0.083215749855` | PASS |

## Euro2024 aggregate results

The final packet contains only the selected `full_minus_presence` logistic model in raw and
calibrated forms. The constant baseline is excluded; observed prevalence (`0.075153374233`) is
descriptive context only.

| Variant | Log loss | Brier | ROC AUC | PR AUC |
|---|---:|---:|---:|---:|
| raw | 0.239307508271 | 0.064707399225 | 0.744677970691 | 0.223985679737 |
| calibrated | 0.243112806225 | 0.066029980705 | 0.744677970691 | 0.223985679737 |

The calibrated-minus-raw effect is positive on both proper scores in this holdout. That result is
reported, not used to undo the WC2022 adoption decision.

The paired match-clustered bootstrap used 2,000 replicates, seed `0`, and 95% percentile
intervals:

| Metric | Raw interval | Calibrated interval | Calibrated minus raw interval |
|---|---:|---:|---:|
| Log loss | [0.207095650265, 0.269139852355] | [0.210598611086, 0.273303673707] | [0.000095442006, 0.007815706219] |
| Brier | [0.053985347273, 0.074766555611] | [0.055641037736, 0.075907318637] | [-0.000013107008, 0.002806020149] |

## Reliability-field clarification

The immutable `holdout-metrics.json` schema-version-1 field named
`raw_anchor_reliability` is calibration provenance, not a Euro2024 reliability table. The runner
intentionally copies `decision.payload["raw_anchor_reliability"]` into the top-level result so the
holdout packet carries the adoption evidence. Its five counts total 1,430, which is the WC2022
calibration membership. In this closeout it should be read as
`calibration_raw_anchor_reliability`.

The actual Euro2024 reliability tables are the `reliability` arrays nested under
`variants.raw` and `variants.calibrated`; both have `n = 1304`. The immutable measured artifact is
left unchanged. The separate [schema clarification](wp2.7-holdout-schema-clarification.md) records
the presentation mapping for downstream readers.

## Slices and limitations

The fixed support rule is at least 50 shots, 5 goals, 5 misses, and 10 matches. Supported levels
were:

- body part: Head, Left Foot, Right Foot
- distance: `[0,10)`, `[10,20)`, `[20,30)` StatsBomb coordinate units
- play pattern: From Corner, From Counter, From Free Kick, From Throw In, Regular Play
- shot type: Open Play
- technique: Half Volley, Normal, Volley
- visible angle: `[0.2,0.4)`, `[0.4,0.6)`, `[0.6,+inf)` radians

All other registered levels remained listed as sparse and were not interpreted. Euro2024 is a
tournament holdout, so time and competition composition change together. Aggregate evidence does
not support row-level or causal claims.

## Reproducibility and evidence hashes

- Experiment: `exp-20260809-wp2_7-calibration-holdout`
- Base candidate: `full_minus_presence`; feature set: `geometry+categoricals`
- Execution/reproduction commit: `e8e863947b74bbe8496a9734878941e8b10e30ce`
- Holdout config SHA-256: `d77187ad0bf7e5053d73c2debe0a61b8e1464885b16601d025f43d811267589b`
- Data source commit: `b0bc9f22dd77c206ddedc1d742893b3bbe64baec`
- Source bundle SHA-256: `710ec99da792c946ff53d5730f0235bb03df41fcfc7dd74d1acfd6a574a2c4fa`
- Holdout membership digest: `6a4b02d6bfb9d3c4619239772c089a65455a5cb0299956912d2d520ca639b729`
- WP2.4 model artifact SHA-256: `9aeac9468c00bd1b93c771e454e48ca29e2eb759cf71836182a782d674bfadca`
- WP2.4 artifact manifest SHA-256: `62cade6c3db5d741039de8f1ad53010319f422dcb942c96f16f1db8a498e8e79`

The original supervised audit hash manifest remains authoritative and internally consistent for
the measured files. These closeout documents are presentation-only additions and are deliberately
not inserted into that completed run's evidence hash list.

Data provided by StatsBomb.
