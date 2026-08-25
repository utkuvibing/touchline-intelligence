# WP5.1 — Sealed-set target-free structural validation

**Access class:** target-free structural validation only (`target_free_structural_only`). This report contains no shot outcomes, goal counts, conversion rates, model scores or row-level previews, and may never gain any.

- Source commit: `b0bc9f22dd77c206ddedc1d742893b3bbe64baec` (2026-05-26)
- Generated (UTC): 2026-08-25T11:45:08Z
- Registry: `data/model/v2_evaluation_registry.json`
- Provenance: `data/provenance/wp5.1-sealed-sets.json`

| Tournament | Scope | Match file | SHA-256 (first 12) | Matches | Unique IDs | Scope mismatches | Missing keys | Parse |
|---|---|---|---|---:|---:|---:|---:|---|
| Copa America 2024 | 223/282 | `matches/223/282.json` | `058380b9fe90` | 32 | 32 | 0 | 0 | pass |
| AFCON 2023 | 1267/107 | `matches/1267/107.json` | `0c5a7fdd63c9` | 52 | 52 | 0 | 0 | pass |

## Parser success and coordinate bounds (event-embedded locations)

| Tournament | Matches scanned | Event files | Lineup files | Schema failures | Locations scanned | Violations | X range | Y range |
|---|---:|---:|---:|---:|---:|---:|---|---|
| Copa America 2024 | 32 | 32 | 32 | 0 | 99179 | 0 | [0.10, 120.00] | [0.10, 80.00] |
| AFCON 2023 | 52 | 52 | 52 | 0 | 160901 | 0 | [0.10, 120.00] | [0.10, 80.00] |

Admitted bounds are `[0, 120.1] x [0, 80]`; the upper X bound carries the measured source exception `location_x = 120.1` documented in `DATA_SOURCE.md`. A non-zero violation or schema-failure count fails this report.

**Overall: PASS**
