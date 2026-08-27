# WP6.1 feature source contract

## Status and boundary

**Status:** frozen, implemented, and accepted on 2026-08-27.

WP6.1 is the first M6 work package. M5 is complete and merged. This contract and
[`v2_feature_dictionary.json`](../../data/model/v2_feature_dictionary.json) define the
target-free source-observation seam used by later M6 work. They fit no preprocessing, create no
feature matrix, select no bundle, and make no model or outcome claim.

The dictionary's only statuses are `confirmed`, `requires_normalization`, and `unsupported`.
They describe source-observation readiness, not feature admission. Bundle admission and model
evaluation start in WP6.2 or later under the frozen
[WP5.2 protocol](wp5_2-v2-nested-protocol-contract.md).

## Canonical data boundary

`V2ShotContext` is versioned, target-free pre-shot context. It contains source observations and
their explicit missingness only. `V2TrainingExample` wraps a context with a separately loaded
label for later training work. The WP6.1 coverage/audit layer accepts only shot metadata and
`V2ShotContext`; it must neither import nor consume `V2TrainingExample`, labels, or a label loader.

The context loader reads exactly the four development scopes fixed by
[`v2_protocol.json`](../../data/model/v2_protocol.json): WC 2018 `(43, 3)`, Euro 2020 `(55, 43)`,
WC 2022 `(43, 106)`, and Euro 2024 `(55, 282)`. It orders shots deterministically and rejects
sealed or foreign scopes, duplicate shots, malformed required structures, incomplete schema state,
and deployed database targets. It operates in a read-only transaction.

Provider xG may be present in raw upstream material only before ingestion's quarantine boundary.
It is never a context field, derivation input, dictionary feature/output value, audit value, or
training-example value. Raw upstream presence that is explicitly ignored or quarantined is not an
error. Any attempt for it to cross into the canonical context boundary, including through a residual
mapping or serialized context, is an error.

The existing v1 `ShotRow`, v1 artifacts, serving runtime, and `/model/predict` public contract are
unchanged. Geometry reuses the [WP2.2 geometry contract](wp2_2-geometry-contract.md); this work
does not reinterpret coordinate units, source facts, freeze frames, StatsBomb 360, or tracking.

## Source derivation rules

- Pre-shot score is reconstructed only from earlier recorded scoring events in the same match. It
  never reads final match scores. Own-goal handling must be explicit; an unresolved required score
  relation fails rather than being guessed.
- Match clock preserves recorded period/clock facts. Possession duration and action count use only
  earlier events in the shot's recorded possession. The preceding event is the immediately prior
  same-possession event in stable source order; a first event remains missing.
- Displacement uses recorded locations only. No endpoint, player, or position may be invented.
  A source end-zone observation is currently unsupported because the typed event schema does not
  establish universal event-end coordinates.
- Key-pass attributes are exposed only after a same-match referenced event resolves safely and its
  individual source semantics are verified. An absent reference remains absent; a broken required
  reference fails.
- F3 uses event-embedded shot freeze frames only. It is not continuous tracking or StatsBomb 360.
  Actors retain their source shape, order, teammate flag, optional position, and optional location;
  no player or position is inferred.

## Audit and evidence contract

The audit reports only source coverage: per-observation and per-tournament availability, invalid
structures, freeze-frame usability, goalkeeper-identification coverage, and missingness signatures.
It contains no labels, conversion summaries, predictions, or model metrics. The deterministic
evidence format is [`wp6.1-source-coverage.md`](../../reports/wp6.1-source-coverage.md).

No F1 spline is fitted in WP6.1. The intended F1 bases remain fold-fitted in future work, including
the predeclared distance-angle interaction/bounded two-dimensional basis. F3 is not admitted here:
its later gate still requires source-verified coordinate semantics, deterministic transforms, and
the coverage conditions stated in `docs/PLAN.md`.

Data provided by StatsBomb.
