# WP2.4 experiment run

Experiment: exp-20260805-wp2_4-baselines

Code commit: 81d4a56395985cb427fbcd13f38a0eb8c42e8be6
Reproduction commit: 81d4a56395985cb427fbcd13f38a0eb8c42e8be6
Input config: experiments/run-configs/wp2_4-baselines.json

Hypothesis: a regularized logistic regression over the locked feature set beats both baselines under PLAN §4.1; presence indicators are admissible only if the D5 protocol passes. The shipped artifact is the D5-selected candidate, never the rejected one.

Published evidence for this run:

- `metrics.json` — the measured protocol result, the D5 decision and the shipped candidate;
- `artifact-manifest.json` — the shipped bundle identity, its hashes and the recreation commands;
- `config.json` — the resolved run-configuration snapshot;
- `reports/wp2.4-baselines-evidence.md` — the reviewable WP2.4 evidence report.

The pre-registered D1-D11 decisions live in the repository-internal modelling contract, which is deliberately not published; every decision they fix is restated in the public evidence report above.
