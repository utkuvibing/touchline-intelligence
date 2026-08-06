"""Model-development infrastructure.

WP2.3 holds the deterministic match-grouped split assignment; preprocessing, baselines, training,
evaluation and the serialized inference artifacts belong to WP2.4 and WP2.5.

Importing this package has **no side effects**. WP2.5's OpenMP thread pin lives in
``touchline.boosting_bootstrap``, the launcher that needs it, so that importing the WP2.3 split
code or the WP2.4 logistic code — neither of which is affected by the thread count — never mutates
the process environment and never fails because the operator set it differently.
"""
