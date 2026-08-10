# Shot-quality model card — WP2.7

## Intended use

A selected-logistic shot-conversion probability for research and analyst decision support; Platt calibration is adopted only when the frozen WC2022 rule passes. It is not StatsBomb's xG model.

## Model and data

The base estimator is the selected `full_minus_presence` regularized logistic model fitted on WC2018 + Euro2020 only. Platt parameters are fitted on WC2022 only. Euro2024 is a tournament holdout. Registered artifact and current execution identities are verified before access.

## Holdout result

The pre-holdout adopted variant was `calibrated`. The holdout reports raw and calibrated effects without selecting between them.

Distance is expressed in StatsBomb coordinate units; visible goal angle is in radians. The paired match bootstrap uses 2,000 replicates and seed 0. Sparse slice levels are not interpreted.
