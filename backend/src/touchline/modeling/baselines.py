"""Constant-prediction baseline under the WP2.3 protocol.

The baseline the WP2.4 candidates must beat is the **training-fold goal rate**, estimated from
```training rows only```. It is explicitly NOT the full-cohort descriptive prevalence returned by
the public ``/baseline`` endpoint: using the full-cohort rate as a per-fold prediction would
contaminate each validation fold with its own outcomes whenever the fold's matches span the whole
cohort. ``ConstantBaseline.fit`` therefore takes exactly the labels of the training fold and
nothing else, and ``predictions`` repeats that single rate.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

IntArray = npt.NDArray[np.int_]
FloatArray = npt.NDArray[np.float64]


class EmptyTrainingError(ValueError):
    """fit() was called with no rows; a training fold must contain at least one shot."""


class ConstantBaseline:
    """A per-fold constant probability equal to the training-fold goal rate.

    Frozen and hashable so a wrongly-computed rate cannot be mutated after the fact; the rate is
    set once at fit from the training labels only.
    """

    __slots__ = ("rate",)

    def __init__(self, rate: float) -> None:
        self.rate = float(rate)

    @classmethod
    def fit(cls, y_train: Sequence[float] | IntArray) -> ConstantBaseline:
        labels = np.asarray(y_train, dtype=np.float64)
        if labels.size == 0:
            raise EmptyTrainingError("a constant baseline needs at least one training row")
        return cls(rate=float(labels.mean()))

    def predictions(self, n: int) -> FloatArray:
        """A length-``n`` vector of the constant training-fold rate."""
        return np.full(n, self.rate, dtype=np.float64)

    def __hash__(self) -> int:
        return hash(self.rate)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ConstantBaseline) and self.rate == other.rate
