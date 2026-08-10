# WP2.7 calibration and holdout evidence

The holdout packet evaluates only the selected `full_minus_presence` logistic model in raw and calibrated forms.
The constant baseline is absent; observed prevalence is descriptive context only.

- Adopted variant (frozen before holdout): `calibrated`
- Rows: 1304
- Matches: 51
- Goals: 98
- Misses: 1206
- Observed prevalence: 0.075153374233

| Variant | Log loss | Brier |
|---|---:|---:|
| raw | 0.239307508271 | 0.064707399225 |
| calibrated | 0.243112806225 | 0.066029980705 |

All real holdout assertions, scoring, bootstrap, slices, and evidence generation were performed inside the single supervised `wp2-7-holdout` execution.
