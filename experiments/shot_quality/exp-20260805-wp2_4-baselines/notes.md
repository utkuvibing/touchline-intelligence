# WP2.4 experiment run

Experiment: exp-20260805-wp2_4-baselines

Code commit: 8cb7a61297a730033a9dcadecc97e665cf17afcf
Reproduction commit: 8cb7a61297a730033a9dcadecc97e665cf17afcf
Input config: experiments\run-configs\wp2_4-baselines.json

Hypothesis: a regularized logistic regression over the locked feature set beats both baselines under PLAN §4.1; presence indicators are admissible only if the D5 protocol passes. The shipped artifact is the D5-selected candidate, never the rejected one.

See metrics.json for the measured protocol result and the shipped candidate; see docs/modeling/wp2_4-baselines-and-logistic-contract.md for the pre-registered decisions.
