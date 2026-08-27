# WP6.1 source coverage audit

**Status:** prior measurement retained for comparison; final-HEAD rerun pending.

This is a deterministic, target-free evidence format for WP6.1. It may report only metadata and
`V2ShotContext` coverage. It must not import or consume training examples, labels, label loaders,
predictions, conversion summaries, or model metrics.

- Source commit: `b0bc9f22dd77c206ddedc1d742893b3bbe64baec`
- Context contract: `1.0`
- Feature dictionary: `data/model/v2_feature_dictionary.json`
- Scope registry: `data/model/v2_protocol.json` development pool only
- Transaction requirement: explicitly configured local database; `READ ONLY`; deployed target refused
- Machine-readable report: [`wp6.1-coverage.json`](wp6.1-coverage.json)
- Report SHA-256: `f771edbe5c7edb80374dc905b6101a28458df8e48d53c42ca416e9a080de9c79`
- Determinism: two consecutive audit runs produced the same SHA-256
- Measurement state: **passed**

## Required scope and context anchors

| Tournament | Scope | Eligible contexts | Ordering/duplicates | Measurement |
|---|---|---:|---|---|
| WC 2018 | 43/3 | 1,638 | deterministic, no duplicates | passed |
| Euro 2020 | 55/43 | 1,234 | deterministic, no duplicates | passed |
| WC 2022 | 43/106 | 1,430 | deterministic, no duplicates | passed |
| Euro 2024 | 55/282 | 1,304 | deterministic, no duplicates | passed |
| Total | four development scopes | 5,606 | deterministic, no duplicates | passed |

## Required coverage output

The table below aggregates feature-context cells within each bundle. `A` means available, `M`
means absent, and `U` means unsupported. The JSON report retains separate available, absent,
invalid, and unsupported counts for every observation and tournament. Missing values were not
replaced with zero, false, or inferred facts.

| Observation group | WC 2018 | Euro 2020 | WC 2022 | Euro 2024 | Overall | Measurement |
|---|---|---|---|---|---|---|
| F0 source observations | A 8,876 / M 2,590 | A 6,869 / M 1,769 | A 7,856 / M 2,154 | A 7,287 / M 1,841 | A 30,888 / M 8,354 | measured |
| F1 source inputs | A 4,914 / M 0 | A 3,702 / M 0 | A 4,290 / M 0 | A 3,912 / M 0 | A 16,818 / M 0 | source inputs only |
| F2 event and sequence observations | A 14,693 / M 1,687 / U 1,638 | A 11,116 / M 1,224 / U 1,234 | A 12,897 / M 1,403 / U 1,430 | A 11,717 / M 1,323 / U 1,304 | A 50,423 / M 5,637 / U 5,606 | measured |
| F3 embedded freeze-frame observations | A 9,826 / M 2 | A 7,404 / M 0 | A 8,580 / M 0 | A 7,824 / M 0 | A 33,634 / M 2 | measured, not admitted |
| Invalid source structures | 0 | 0 | 0 | 0 | 0 | passed |
| Usable freeze frames | 1,638 | 1,234 | 1,430 | 1,304 | 5,606 | 100% |
| Shots with identified recorded goalkeeper | 1,637 | 1,234 | 1,430 | 1,304 | 5,605 | one WC 2018 absence |

The missingness signatures were 4,128 complete contexts, 1,260 with no resolved key pass, and 218
with neither a preceding same-possession action nor a resolved key pass. Dictionary statuses were
14 `confirmed`, 12 `requires_normalization`, and one `unsupported` observation.

## Required failure conditions

The audit fails rather than emitting coverage if it encounters a sealed or foreign scope, duplicate
shot identifier, malformed required structure, unresolved required relation, incomplete schema,
deployed database target, or prohibited value at the canonical context boundary. Upstream raw
provider-xG presence that ingestion explicitly ignores or quarantines is permitted; a value crossing
into context, a derivation, dictionary output, or audit calculation is not.

This audit establishes no bundle admission. It records source-observation coverage only; any
unsupported or ambiguous observation is a negative result for the source audit, not permission to
substitute an inferred value.

Data provided by StatsBomb.
