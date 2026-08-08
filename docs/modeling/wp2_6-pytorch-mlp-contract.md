# WP2.6 PyTorch MLP contract

ADR 0012 owns the decisions. This document is the executable acceptance map.

## Locked scientific inputs

- Development only: WC 2018 and Euro 2020, 2,872 shots in 115 matches.
- Saved match-grouped folds: 570 / 552 / 602 / 576 / 572 validation rows.
- Existing binary `ShotRow.y` target and development-wide label-free vocabulary.
- The sixteen WP2.4 `geometry+categoricals` columns; no presence indicators.
- Fold-training-only continuous scaler and existing metrics/reliability implementation.
- No calibration fitting, WC 2022 labels, Euro 2024 access, weighting, resampling or retuning.

## Estimator and fit

`16 -> Linear(8) -> ReLU -> Linear(1)` returns one logit. Kaiming-uniform first-layer weights and
zero bias; Xavier-uniform output weights and zero bias; float32 throughout. The fixed optimizer,
loader and 200-epoch contract is stated in ADR 0012 and must be passed explicitly in code.

Every fold and final refit resets seed 0 before model construction and uses its own seed-0 loader
generator. Training uses `train`, autograd and finite checks; evaluation uses `eval` and
`torch.no_grad`. Sigmoid is applied exactly once outside `forward`.

## Evidence and selection

CPU OOF evidence is canonical and must reproduce in two fresh no-write processes. Existing WP2.4
candidates and WP2.5's selected booster reproduce to twelve decimals. Chain B compares
`full_minus_presence` with `pytorch_mlp`; all four inherited replacement conditions must pass or the
logistic remains selected. CUDA runs are qualification evidence only.

Only after OOF selection is frozen may all 2,872 development rows fit the candidate scaler and
model. Local artifact paths are `artifacts/models/<experiment-id>/weights.pt` and `metadata.json`.
Canonical measurement first writes only under the ignored model-artifact tree. It may not touch the
tracked experiment directory or results ledger. Committed manifests identify weights, parameters,
preprocessing, code, data, config, lock, CPU/CUDA runtimes, qualification-record hash and exact
recreation commands. The results ledger writes `model_pickle_sha256=n/a` without changing its header.

Qualification is supervised, not inferred from individual successful commands: two fresh CPU
reproduction payloads and two fresh CUDA payloads must agree within device, strictly reload the
canonical state dictionary and committed preprocessing identity, and pass same-weight cross-device
probability parity. The CPU payload must also exactly reproduce canonical MLP metrics, ordered OOF
predictions, fold parameter digests, complete training history, final parameters and selection.
Only after all checks pass may `uv run poe qualify-mlp` atomically publish the tracked evidence set,
the experiment-local `cuda-qualification.json`, and the single `status=complete` ledger row.

## Execution gate

Synthetic/unit/CI-equivalent tests are allowed while ADR 0012 is proposed. Loading the real cohort,
writing official experiment records, accepting the ADR, or claiming a measured result is not.
