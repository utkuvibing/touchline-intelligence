# WP5.1 — v1 release freeze record

**Status:** frozen 2026-08-25. v1 (`exp-20260810-wp2_8-release`) remains the production incumbent
until an M7 external qualification gate proves a replacement; nothing in this freeze redeploys or
reopens it.

- **Served release:** `exp-20260810-wp2_8-release` (release status `m2_qualified`)
- **Freeze tag:** `v1-release-frozen`
- **Source pin:** StatsBomb Open Data `b0bc9f22dd77c206ddedc1d742893b3bbe64baec` (2026-05-26)

## Verified artifact identities

Every SHA-256 below was recomputed from the working tree on 2026-08-25 and matched the value
recorded in `experiments/shot_quality/exp-20260810-wp2_8-release/config.json`.

| Artifact | SHA-256 |
|---|---|
| `experiments/run-configs/wp2_4-baselines.json` | `30d34981d957f2b7c3832b2fe347f10986a6f14e58cca98a4abba673a56b0b0e` |
| `…/exp-20260805-wp2_4-baselines/config.json` | `b4e68bb0d2850770a9661fe19839a66695b328aafc9a9e58e40f5baab88eb394` |
| `…/exp-20260805-wp2_4-baselines/metrics.json` | `00b8785b25c03758a93416b0edf461adf1584fc06b20be1f75ba702019a67e5c` |
| `…/exp-20260805-wp2_4-baselines/artifact-manifest.json` | `62cade6c3db5d741039de8f1ad53010319f422dcb942c96f16f1db8a498e8e79` |
| `artifacts/models/exp-20260805-wp2_4-baselines/model.pkl` | `9aeac9468c00bd1b93c771e454e48ca29e2eb759cf71836182a782d674bfadca` |
| `data/model/wp2_3_match_assignments.csv` | `e2d5517d96aa81d2229e1ef00a3c692f44f280630c3e75b7f6735e7cdc1787d8` |
| `…/wp2_7-calibration-holdout/calibration-decision.json` | `a88255ca56b478372ec76bc9dddb3295d9073a7f180d5dc8f0d9fa34bfd65d87` |
| `…/wp2_7-calibration-holdout/holdout-access-audit.json` | `830d53c29b8d6bb5521995c5deab8d9f9cffa7997c2f2584ecfc3631f65c4939` |
| `…/wp2_7-calibration-holdout/holdout-metrics.json` | `3443b4a5e19fd87b1ee599502152a7dcfe1af3d8466c09ad7cbf2bb8cae2e674` |
| `…/wp2_7-calibration-holdout/experiment-record.json` | `6c3ede22ac846d59360676a32f4b16f0fbf0e31c832e5d962ca8a741cffbb40a` |

The model pickle lives under the git-ignored `artifacts/` tree; its hash is recorded here so any
later copy can be verified byte-for-byte against this freeze.

## What the freeze means

- The v1 model bundle, evaluation packets and public claims are immutable historical evidence.
  Reported results are never rewritten for presentation.
- Euro 2024 remains the one-time v1 holdout under ADR 0013. It stays untouched for all *v1*
  claims, but is part of the v2 development pool and is no longer claimed as untouched there.
- v2 development proceeds only under the sealed-set rules in
  `data/model/v2_evaluation_registry.json`; AFCON 2023 and Copa América 2024 permit
  target-free structural validation only until M7 opens their one-time qualification run.

## Sealed assets created by WP5.1

- Registry: `data/model/v2_evaluation_registry.json`
- Structural validation report: `reports/wp5.1-sealed-structural-validation.md` (**PASS**,
  zero schema failures, zero coordinate-bound violations across both tournaments)
- Provenance: `data/provenance/wp5.1-sealed-sets.json`
- Future reservation: none available at the pinned revision ⇒ further model-selection claims
  freeze after M7 unless a future pinned revision adds a genuinely untouched complete men's
  tournament (recorded in the registry's `future_reservation`).
