# WP2.7 shot-quality model card

**Status:** pre-registered, not executed.

## Intended use

Research and analyst decision support for selected-logistic shot-conversion probability. Platt
calibration is adopted only when the frozen WC2022 rule passes. This is not StatsBomb's xG model and
must not be interpreted as a provider model.

## Model and data contract

The base estimator is the selected `full_minus_presence` regularized logistic model fitted only on
WC2018 + Euro2020 under the all-development preprocessing contract. WC2022 may fit only Platt
calibration parameters. Euro2024 is a tournament holdout: it may transform and score, but cannot
refit, select, or alter the base model or calibration choice.

Real execution requires the exact registered artifact/manifest and clean current code, config, and
lock provenance. Platt parameters are serialized without display rounding. The holdout bootstrap is
fixed at 2,000 match-clustered paired replicates with seed `0`.

The adoption choice is frozen from raw-anchor WC2022 reliability groups before Euro2024 access. The
holdout packet reports raw and calibrated selected-logistic predictions and their paired effect; it
does not choose between them. The constant baseline is not in that packet. Observed prevalence is
descriptive context only.

Distance is expressed in StatsBomb coordinate units and visible goal angle in radians. Sparse slice
levels are not interpreted. Euro2024 is a tournament holdout, so time and competition composition
change together.

## Results

No WC2022 or Euro2024 rows were accessed while this model card was authored. Metrics, calibration
parameters, supported slices, and bootstrap intervals will be populated only by the supervised
WP2.7 commands and must not be inferred from this pre-registration.
