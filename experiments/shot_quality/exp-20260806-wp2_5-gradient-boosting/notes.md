# WP2.5 experiment run

Experiment: exp-20260806-wp2_5-gradient-boosting

Code commit: 4fc0031c1e1c19dd6e110bbd2bd8e82ef5c36aca
Reproduction commit: 4fc0031c1e1c19dd6e110bbd2bd8e82ef5c36aca
Input config: experiments/run-configs/wp2_5-gradient-boosting.json

Hypothesis: one gradient-boosting model, tuned over a twelve-point declared grid on the locked development folds and the shipped WP2.4 feature columns, replaces the regularized logistic regression under PLAN 4.1. The rule is applied twice: continuity with the WP2.4 chain, and a direct comparison against the shipped logistic which is the decision of record. A negative result is published as a result.

Published evidence for this run:

- `metrics.json` — the measured protocol result, both replacement chains, the declared grid and its scores;
- `artifact-manifest.json` — the boosting bundle identity, its hashes and the recreation commands;
- `config.json` — the resolved run-configuration snapshot;
- `reports/wp2.5-gradient-boosting-evidence.md` — the reviewable WP2.5 evidence report.

The pre-registered D12-D21 decisions live in the repository-internal modelling contract, which is deliberately not published; every decision they fix is restated in the public evidence report above.
