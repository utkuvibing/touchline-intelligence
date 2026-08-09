"""Stable, importable inference artifact for the WP2.4 shipped model.

The training entry point is ``python -m touchline.modeling.train``. A class defined *inside that
executing module* would be pickled with the identity ``__main__.ArtifactBundle``, which any later
process can fail to resolve when it imports ``touchline.modeling.train`` instead. The artifact and
its load/inference API therefore live in this dedicated, always-importable module: the persisted
class identity is ``touchline.modeling.artifact.ArtifactBundle`` regardless of how training was
launched (blocking correction P0).

The bundle is self-contained: estimator, all-development scaler, locked development vocabulary,
complete encoded column order, the selected shipped feature columns and their indices, reference
and rare-level mappings, and the hashes that identify the training inputs. It scores raw
``ShotRow`` values with persisted preprocessing only; nothing is re-fitted at inference time.

**Feature-column contract (blocking correction P1).** Before slicing, prediction re-encodes the
rows and compares the encoder's current column names against the persisted ``all_columns``,
especially column order, and checks uniqueness, index bounds, selected-name/index agreement and the
estimator's feature count. Any ambiguous schema mismatch raises ``ArtifactCompatibilityError``
instead of silently feeding the estimator the wrong columns — including a **negative**
``selected_indices`` entry, which Python would otherwise wrap around into a valid-looking but wrong
column, and an out-of-range entry, which would otherwise escape as a bare ``IndexError``.

The artifact schema is versioned via ``artifact_schema_version``; a bundle created under an
unsupported version fails loudly on load and on predict.
"""

from __future__ import annotations

import pickle
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
from sklearn.ensemble import HistGradientBoostingClassifier  # type: ignore[import-untyped]
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]

from touchline.modeling.preprocessing import ShotRow, StandardScaler, Vocabulary, encode_rows

__all__ = [
    "ArtifactBundle",
    "ArtifactCompatibilityError",
    "BoostingBundle",
    "artifact_schema_version",
    "boosting_artifact_schema_version",
    "infer",
    "infer_boosting",
    "infer_logit",
    "load_boosting_bundle",
    "load_bundle",
    "validate_column_contract",
]

FloatArray = npt.NDArray[np.float64]

#: Bumped whenever the bundle layout or its compatibility checks change materially. A bundle whose
#: schema version is not this exact value must fail loudly on load and on predict.
artifact_schema_version = 1


class ArtifactCompatibilityError(ValueError):
    """The artifact cannot be used for inference because its persisted contract no longer matches.

    Distinct from a generic ``ValueError`` so that schema/feature mismatches can be caught and
    reported precisely instead of being mistaken for a modelling error.
    """


def validate_column_contract(
    *,
    all_columns: Sequence[str],
    selected_columns: Sequence[str],
    selected_indices: Sequence[int],
    current_columns: Sequence[str],
    n_features_in: int,
) -> None:
    """Fail loudly if the encoder's columns no longer match a persisted feature contract.

    Ordering, membership (missing/unexpected), uniqueness, index bounds, selected-name/index
    agreement and the estimator's feature count are all checked. The artifact is never silently
    reordered, and no index mismatch is allowed to surface as a bare ``IndexError``.

    Shared by every bundle family so the logistic and boosting artifacts cannot drift apart on the
    one check that stands between a schema change and silently scoring the wrong columns. It is a
    module-level function, not a method, so adding a second bundle class does not duplicate it —
    and because methods are not pickled, hoisting it left ``ArtifactBundle``'s persisted bytes
    untouched.
    """
    all_cols = list(all_columns)
    if len(all_cols) != len(set(all_cols)):
        raise ArtifactCompatibilityError(
            "persisted all_columns contains duplicate column names; contract is ambiguous"
        )
    current = list(current_columns)
    if len(current) != len(set(current)):
        raise ArtifactCompatibilityError(
            "encoder returned duplicate column names; the schema contract is ambiguous"
        )
    if current != all_cols:
        raise ArtifactCompatibilityError(
            "encoder column names/order no longer match the persisted all_columns "
            f"(current has {len(current)} names, persisted {len(all_cols)}); refusing to "
            "infer on an ambiguous feature schema"
        )
    if len(selected_indices) != len(set(selected_indices)):
        raise ArtifactCompatibilityError(
            "persisted selected_indices contain duplicates; the feature selection is ambiguous"
        )
    # Bounds must be checked before the indices are used. A negative index would silently
    # wrap around and select a different column (no exception at all), and an out-of-range
    # index would surface as a bare ``IndexError`` that reads like an internal bug rather
    # than the artifact-compatibility failure it is.
    out_of_range = [index for index in selected_indices if index < 0 or index >= len(all_cols)]
    if out_of_range:
        raise ArtifactCompatibilityError(
            f"persisted selected_indices {out_of_range} are outside the persisted "
            f"all_columns range [0, {len(all_cols)}); refusing to infer on an out-of-bounds "
            "feature selection"
        )
    expected_selected = [all_cols[index] for index in selected_indices]
    if list(selected_columns) != expected_selected:
        raise ArtifactCompatibilityError(
            "persisted selected_columns do not match selected_indices into all_columns; "
            "refusing to infer on an inconsistent feature selection"
        )
    if len(selected_columns) != len(set(selected_columns)):
        raise ArtifactCompatibilityError(
            "persisted selected_columns contain duplicates; the feature selection is ambiguous"
        )
    if n_features_in != len(selected_columns):
        raise ArtifactCompatibilityError(
            f"estimator was fitted on {n_features_in} features but the "
            f"artifact selects {len(selected_columns)}; refusing to infer"
        )


@dataclass(frozen=True)
class ArtifactBundle:
    """The persisted, self-contained inference artifact. Top-level in this importable module.

    Field names are part of the serialization contract; see the module docstring. Every field is
    persisted with the pickle, so ``load_bundle`` restores a fully usable artifact with no access
    to the development database.
    """

    schema_version: int
    experiment_id: str
    shipped_candidate: str
    best_c: float
    code_commit: str
    reproduction_commit: str
    data_source_commit: str
    cohort_sql_sha256: str
    assignments_sha256: str
    input_config_sha256: str
    uv_lock_sha256: str
    estimator: LogisticRegression
    scaler: StandardScaler
    vocabulary: Vocabulary
    all_columns: tuple[str, ...]
    selected_columns: tuple[str, ...]
    selected_indices: tuple[int, ...]
    reference_levels: Mapping[str, str]
    rare_mapping: Mapping[str, tuple[str, ...]]

    def predict_proba(self, rows: Sequence[ShotRow]) -> FloatArray:
        """Goal probabilities for raw rows, using the persisted preprocessing (never a refit)."""
        self._require_supported_schema()
        full, current_columns = encode_rows(rows, self.vocabulary, self.scaler)
        self._validate_feature_contract(current_columns)
        subset = full[:, list(self.selected_indices)]
        return np.asarray(self.estimator.predict_proba(subset), dtype=np.float64)[:, 1]

    def predict_logit(self, rows: Sequence[ShotRow]) -> FloatArray:
        """Return the frozen estimator's raw linear score without fitting anything."""
        self._require_supported_schema()
        full, current_columns = encode_rows(rows, self.vocabulary, self.scaler)
        self._validate_feature_contract(current_columns)
        subset = full[:, list(self.selected_indices)]
        return np.asarray(self.estimator.decision_function(subset), dtype=np.float64).reshape(-1)

    def _require_supported_schema(self) -> None:
        if self.schema_version != artifact_schema_version:
            raise ArtifactCompatibilityError(
                f"artifact schema version {self.schema_version} is unsupported; "
                f"expected {artifact_schema_version}"
            )

    def _validate_feature_contract(self, current_columns: Sequence[str]) -> None:
        """Delegate to the shared column-contract validator (see ``validate_column_contract``)."""
        validate_column_contract(
            all_columns=self.all_columns,
            selected_columns=self.selected_columns,
            selected_indices=self.selected_indices,
            current_columns=current_columns,
            n_features_in=self.estimator.n_features_in_,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "artifact_schema_version": self.schema_version,
            "experiment_id": self.experiment_id,
            "shipped_candidate": self.shipped_candidate,
            "best_c": self.best_c,
            "code_commit": self.code_commit,
            "reproduction_commit": self.reproduction_commit,
            "data_source_commit": self.data_source_commit,
            "cohort_sql_sha256": self.cohort_sql_sha256,
            "assignments_sha256": self.assignments_sha256,
            "input_config_sha256": self.input_config_sha256,
            "uv_lock_sha256": self.uv_lock_sha256,
            "n_features": len(self.selected_columns),
            "all_columns": list(self.all_columns),
            "selected_columns": list(self.selected_columns),
            "selected_indices": list(self.selected_indices),
            "reference_levels": dict(self.reference_levels),
            "rare_mapping": {k: list(v) for k, v in self.rare_mapping.items()},
        }


#: Pin the pickle identity explicitly so a future refactor cannot silently re-bind the class to an
#: executable ``__main__`` module. This is the exact property the cross-process regression test and
#: the mutation suite protect.
ArtifactBundle.__module__ = "touchline.modeling.artifact"


def infer(bundle: ArtifactBundle, rows: Sequence[ShotRow]) -> FloatArray:
    """The explicit inference entry point: raw ``ShotRow`` values to goal probabilities.

    Applies the persisted scaler and vocabulary, validates the persisted feature-column contract,
    restricts to the persisted selected columns, and returns ``P(goal)``. No preprocessing is
    re-fitted at inference time.
    """
    return bundle.predict_proba(rows)


def infer_logit(bundle: ArtifactBundle, rows: Sequence[ShotRow]) -> FloatArray:
    """The explicit inference entry point for the frozen base linear score."""
    return bundle.predict_logit(rows)


def load_bundle(path: str | Path) -> ArtifactBundle:
    """Load a previously generated artifact from a trusted location.

    Only ``ArtifactBundle`` instances from this module, under a supported schema version, are
    accepted. A bare estimator or a loosely-related object is refused (blocking correction P0).
    """
    with open(path, "rb") as handle:
        obj = pickle.load(handle)
    if not isinstance(obj, ArtifactBundle):
        raise ArtifactCompatibilityError(
            f"pickle at {path} is not a touchline.modeling.artifact.ArtifactBundle (got "
            f"{type(obj).__module__}.{type(obj).__qualname__})"
        )
    obj._require_supported_schema()
    return obj


#: WP2.5's boosting artifact carries its **own** schema version, deliberately separate from
#: ``artifact_schema_version``. ``ArtifactBundle`` is not modified by WP2.5: bumping a shared
#: version — or adding a field to the logistic bundle — would change its pickled bytes and make the
#: ``model_pickle_sha256`` published in WP2.4's evidence unreproducible.
#:
#: Version 2 renamed ``shipped_candidate`` to ``artifact_candidate`` and added
#: ``selection_incumbent``. Version 1 used ``shipped_candidate`` for *what the bundle contains*,
#: while the metrics, manifest and results row used the same word for *which candidate won the
#: comparison* — two different things under one name, which is exactly the confusion the split
#: fields now prevent.
boosting_artifact_schema_version = 2


@dataclass(frozen=True)
class BoostingBundle:
    """The persisted, self-contained inference artifact for the WP2.5 boosting candidate.

    Structurally parallel to :class:`ArtifactBundle` and validated by the same
    :func:`validate_column_contract`, but a distinct class: the two families differ in the
    estimator type and in what identifies the selected model (a hyperparameter mapping rather than
    a single ``C``), and keeping them separate is what leaves WP2.4's artifact byte-identical.
    """

    schema_version: int
    experiment_id: str
    #: What this bundle **contains** — the candidate whose fitted estimator is serialized here.
    artifact_candidate: str
    #: Which candidate **won** the comparison that produced it. Recorded because a reader holding
    #: only the pickle should be able to tell whether this model was adopted, and deliberately
    #: named differently from :attr:`artifact_candidate` because the two can disagree: WP2.5 built
    #: a booster and the logistic regression won.
    selection_incumbent: str
    hyperparameters: Mapping[str, float]
    code_commit: str
    reproduction_commit: str
    data_source_commit: str
    cohort_sql_sha256: str
    assignments_sha256: str
    input_config_sha256: str
    uv_lock_sha256: str
    estimator: HistGradientBoostingClassifier
    scaler: StandardScaler
    vocabulary: Vocabulary
    all_columns: tuple[str, ...]
    selected_columns: tuple[str, ...]
    selected_indices: tuple[int, ...]
    reference_levels: Mapping[str, str]
    rare_mapping: Mapping[str, tuple[str, ...]]

    def predict_proba(self, rows: Sequence[ShotRow]) -> FloatArray:
        """Goal probabilities for raw rows, using the persisted preprocessing (never a refit)."""
        self._require_supported_schema()
        full, current_columns = encode_rows(rows, self.vocabulary, self.scaler)
        self._validate_feature_contract(current_columns)
        subset = full[:, list(self.selected_indices)]
        return np.asarray(self.estimator.predict_proba(subset), dtype=np.float64)[:, 1]

    def _require_supported_schema(self) -> None:
        if self.schema_version != boosting_artifact_schema_version:
            raise ArtifactCompatibilityError(
                f"boosting artifact schema version {self.schema_version} is unsupported; "
                f"expected {boosting_artifact_schema_version}"
            )

    def _validate_feature_contract(self, current_columns: Sequence[str]) -> None:
        """Delegate to the shared column-contract validator (see ``validate_column_contract``)."""
        validate_column_contract(
            all_columns=self.all_columns,
            selected_columns=self.selected_columns,
            selected_indices=self.selected_indices,
            current_columns=current_columns,
            n_features_in=self.estimator.n_features_in_,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "boosting_artifact_schema_version": self.schema_version,
            "experiment_id": self.experiment_id,
            "artifact_candidate": self.artifact_candidate,
            "selection_incumbent": self.selection_incumbent,
            "hyperparameters": dict(self.hyperparameters),
            "code_commit": self.code_commit,
            "reproduction_commit": self.reproduction_commit,
            "data_source_commit": self.data_source_commit,
            "cohort_sql_sha256": self.cohort_sql_sha256,
            "assignments_sha256": self.assignments_sha256,
            "input_config_sha256": self.input_config_sha256,
            "uv_lock_sha256": self.uv_lock_sha256,
            "n_features": len(self.selected_columns),
            "all_columns": list(self.all_columns),
            "selected_columns": list(self.selected_columns),
            "selected_indices": list(self.selected_indices),
            "reference_levels": dict(self.reference_levels),
            "rare_mapping": {k: list(v) for k, v in self.rare_mapping.items()},
        }


#: Same identity pin as ``ArtifactBundle``: the persisted class must never become ``__main__``.
BoostingBundle.__module__ = "touchline.modeling.artifact"


def infer_boosting(bundle: BoostingBundle, rows: Sequence[ShotRow]) -> FloatArray:
    """The explicit inference entry point for the boosting artifact."""
    return bundle.predict_proba(rows)


def load_boosting_bundle(path: str | Path) -> BoostingBundle:
    """Load a previously generated boosting artifact from a trusted location.

    Only ``BoostingBundle`` instances from this module, under a supported schema version, are
    accepted — an ``ArtifactBundle`` is refused too, so the two families cannot be confused.
    """
    with open(path, "rb") as handle:
        obj = pickle.load(handle)
    if not isinstance(obj, BoostingBundle):
        raise ArtifactCompatibilityError(
            f"pickle at {path} is not a touchline.modeling.artifact.BoostingBundle (got "
            f"{type(obj).__module__}.{type(obj).__qualname__})"
        )
    obj._require_supported_schema()
    return obj
