# ADR 0005: Bounded PyTorch artifact and pre-registered model selection

## Status

Accepted — 2026-07-31

## Context

Deep-learning frameworks appear as essential in 8 of 30 scanned job postings and as desirable in 2
more, concentrated in ML-engineer roles. The original plan prohibited neural networks in every phase.
That prohibition was defensible as an engineering choice on a small tabular problem, but it left the
portfolio with no PyTorch evidence at all.

Two distinct questions had been conflated:

1. *Does the developer gain hands-on PyTorch experience?* — a learning objective.
2. *Does a neural network become the production model, or receive a larger follow-up phase?* — an
   empirical question.

Blocking the first behind evidence for the second was a category error. Separately, on ~4,700 rows of
tabular data with roughly ten features, a small MLP is not expected to beat regularized logistic
regression — which creates a real risk that a selection criterion gets invented after the results are
seen, in whichever direction flatters the outcome.

## Decision

**A bounded PyTorch artifact is mandatory** inside M2 (WP2.6), unconditional on outcome:

- a small MLP written with `Dataset`, `DataLoader` and `nn.Module` — not a wrapper library;
- the **same cohort, features, saved split IDs and metrics** as the classical baselines;
- seeded and config-driven, with one experiment record under `experiments/`;
- reported on the same comparison table: log loss, Brier, discrimination, calibration.

**The hypothesis is pre-registered:** the MLP is expected to match or slightly underperform
regularized logistic regression, with worse cross-fold calibration stability.

**The production-selection rule is fixed before any experiment output is viewed.** A candidate
replaces the incumbent only if **all four** hold on the development folds, never on the holdout:

1. lower mean log loss, by more than the incumbent's own cross-fold standard deviation;
2. lower or equal mean Brier score;
3. no worse calibration — maximum absolute deviation between predicted and observed rate, across
   bins with adequate support, does not increase;
4. not less stable — cross-fold standard deviation of log loss does not increase.

Ties go to the simpler, more interpretable model. The holdout is opened once, after selection.

**A larger sequence or spatial deep-learning phase is rejected on evidence:** the open tracking
universe is roughly 20 matches, and the only cleanly-licensed set (DFL/IDSSE, CC-BY 4.0) is 7. Seven
matches cannot train a sequence model.

## Alternatives considered

- **No PyTorch at all (original plan):** rejected — leaves a named requirement with zero evidence, on
  a project where the marginal cost of a fair comparison is small.
- **PyTorch as the headline model:** rejected — unjustifiable on this data size, and it would replace
  a defensible choice with an indefensible one.
- **Decide the selection criterion after seeing results:** rejected — it violates the project's own
  experiment rules and is exactly the failure mode a reviewer probes for.
- **Wait for tracking data to justify deep learning:** rejected — it blocks a learning objective
  behind an empirical question that turns out to be answerable in the negative anyway.

## Consequences

- The portfolio carries genuine PyTorch evidence, and the honest sentence in an interview becomes
  "I compared it under identical splits, it did not win, and I know why" — which is stronger than
  either omitting it or overclaiming it.
- The comparison table gains a third candidate, at modest cost, on infrastructure that already exists.
- A negative result must be published as a result. That is accepted in advance.
- The developer must be able to explain autograd, `Dataset`/`DataLoader` (including why shuffling
  must not break the match-grouped split), `nn.Module.forward`, `BCEWithLogitsLoss` as log loss,
  optimizer and learning rate, epoch versus batch, overfitting in a training curve, and early
  stopping — unaided.

## Review trigger

The cohort grows by an order of magnitude; a sequential or spatial representation becomes available
with enough matches to train on; or the selection rule's four conditions are jointly met.
