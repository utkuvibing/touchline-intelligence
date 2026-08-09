# ADR 0012: Bounded PyTorch MLP lifecycle

- Status: **accepted — 2026-08-09**
- Date: 2026-08-09
- Owners: WP2.6

## Context

ADR 0005 requires one defensible PyTorch artifact on the identical WP2.3 development population,
folds, WP2.4 shipped features and evaluation protocol. The development cohort has 2,872 shots, so
the engineering lifecycle—not neural capacity or model shopping—is the useful learning objective.

## Decision

WP2.6 pre-registers one `float32` MLP: `Linear(16, 8)`, ReLU, `Linear(8, 1)`, raw logit (145
parameters). It uses explicit initialization, unweighted mean `BCEWithLogitsLoss`, AdamW
(`lr=1e-3`, `weight_decay=1e-4`, betas `(0.9, 0.999)`, epsilon `1e-8`, AMSGrad/foreach/fused false),
200 fixed epochs, batch size 128, shuffled training with a seed-0 generator, unshuffled evaluation,
workers 0 and no dropped rows. There is no early stopping, scheduler, clipping, dropout, batch norm,
AMP, `torch.compile`, calibration, resampling or hyperparameter search.

All five outer folds reuse the saved match IDs. Vocabulary stays development-wide and label-free;
continuous scaling is fit on each fold's training rows only. The exact sixteen
`geometry+categoricals` columns are shared with the logistic and booster; presence indicators stay
excluded. Epoch curves are diagnostic only and epoch 200 alone supplies OOF predictions.

Canonical selection evidence runs on CPU in fresh processes. CUDA qualification runs the same five
fits and an all-development refit twice on the local RTX 4050 but is diagnostic and cannot enter
selection. Deterministic algorithms are hard errors; Python, NumPy, Torch CPU/CUDA and DataLoader
seeds are reset before each fit. CUDA uses `CUBLAS_WORKSPACE_CONFIG=:4096:8` and only PyTorch 2.13's
`fp32_precision="ieee"` API family. CUDA runtime provenance records
`torch.backends.cudnn.version()` and the NVIDIA driver version from a bounded read-only
`nvidia-smi --query-gpu=driver_version` query. Same canonical weights are scored on CPU and CUDA with
`atol=1e-6`, `rtol=1e-5` probability parity.

Chain B compares the MLP directly with `full_minus_presence` logistic under the unchanged four-part
replacement rule. Chain A extends historical continuity through the MLP. No WC 2022 calibration
labels or Euro 2024 rows are loaded. The all-development scaler and final candidate model are fit
only after OOF selection is frozen and never feed back into OOF evidence.

PyTorch 2.13.0 belongs to a default `modeling` dependency group. uv resolves the CPU index on
non-Windows systems and CUDA 13.0 on Windows. Production Docker installs with
`--no-default-groups`, and neither API startup nor shared modeling imports may transitively import
Torch.

The artifact is a strict state dictionary at
`artifacts/models/<experiment-id>/weights.pt` plus local metadata, both ignored. Committed records
carry `weights_sha256`, a serialization-independent parameter digest, and a canonical preprocessing
digest over the final scaler, vocabulary, encoded schema and selected columns. Strict reload requires
that committed preprocessing identity; ignored metadata cannot authenticate itself. The frozen
ledger keeps the inherited shared vocabulary (`date_utc` as a full UTC timestamp,
`dataset_id=wp2_3_split_lock`, `split_strategy=wp2_3_tournament_split`, and
`primary_metric=mean_log_loss`) and `model_pickle_sha256=n/a`; a `.pt` hash must never be placed
under that legacy name. The MLP identity remains in the model-specific `model` field.

The canonical CPU measurement first writes only to ignored artifact staging, leaving the tracked
experiment directory and ledger clean. Two fresh no-write CPU reproductions and two fresh CUDA
qualifications each reload the canonical artifact on their requested device. A separate supervisor
requires exact within-device agreement; exact CPU agreement with canonical metrics, ordered OOF
predictions, fold parameter digests, training history, final parameters and selection; and
same-weight CPU/CUDA probability parity at `atol=1e-6`, `rtol=1e-5`. Only after those checks pass
does it publish the tracked records, qualification record and `status=complete` ledger row. The
published manifest binds the qualification hash, CPU/CUDA runtimes and recreation commands. CUDA
payloads contain no selection chain and have no selection effect.

## Consequences

The experiment can credibly lose. CPU evidence is portable enough for CI and scientific selection;
the CUDA path demonstrates real device-aware training without pretending this tiny workload needs a
GPU. The fixed architecture makes the result interpretable and keeps development-fold reuse
bounded. Training dependencies do not expand the deployed service.

## Acceptance gate

No real-cohort command may run while this ADR remains proposed. Acceptance requires the author to
change the status explicitly after reviewing the implementation and pre-registered config.

## Review triggers

Any change to rows, folds, target, features, preprocessing, architecture, training constants,
device roles, replacement rule, artifact identity, dependency topology, or access to calibration or
holdout data requires a new decision before execution.
