"""Deterministic launcher for WP2.5 training. **This is the official entry point.**

    python -m touchline.boosting_bootstrap --config <path>

Why a launcher exists at all. scikit-learn's ``HistGradientBoostingClassifier`` produces
byte-different serialized models depending on the OpenMP thread count, while its predictions are
unchanged. That was measured on the WP2.5 cohort: one thread and eight threads both give a
174,433-byte pickle with bit-identical predictions, but different bytes. ``model_pickle_sha256`` is
published as the artifact's identity, so the thread count has to be fixed for the **process**, and
fixed before the OpenMP runtime initialises — which happens on the first import of a compiled
dependency that uses it.

This module therefore pins ``OMP_NUM_THREADS`` and only *then* imports the trainer. The import is
deliberately inside :func:`main`, not at module scope, so no import sorter can move it above the
pin.

It lives outside ``touchline.modeling`` on purpose. An earlier version pinned the environment from
``touchline.modeling.__init__``, which meant importing *any* modeling module — including the WP2.3
split code and the WP2.4 logistic code, neither of which is affected by the thread count — mutated
the process environment as a side effect, and raised if the operator had set a different value.
Import should not do that. The pin belongs to the one job that needs it.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

#: The only OpenMP thread count WP2.5 evidence may be produced under (D20).
OMP_THREAD_PIN = "1"

#: The environment variable the OpenMP runtime reads when it initialises.
OMP_ENV_VAR = "OMP_NUM_THREADS"


class ThreadPinError(RuntimeError):
    """The process was started under an OpenMP thread count that cannot reproduce the artifact."""


def pin_openmp_threads() -> None:
    """Fix ``OMP_NUM_THREADS`` at ``1`` for this process, or refuse to continue.

    An inherited value of exactly ``1`` is accepted — that is the same environment. Any other
    inherited value is a loud failure: silently overwriting it would run the estimator under an
    environment the operator did not ask for, and silently accepting it would produce an artifact
    whose published hash nobody else could reproduce. Either way the operator must know, and must
    know before the estimator is imported rather than after an hour of fitting.
    """
    inherited = os.environ.get(OMP_ENV_VAR)
    if inherited is not None and inherited.strip() != OMP_THREAD_PIN:
        raise ThreadPinError(
            f"{OMP_ENV_VAR} is set to {inherited!r}, but WP2.5 training requires "
            f"{OMP_THREAD_PIN!r}: scikit-learn's histogram gradient booster serializes differently "
            "under a different thread count, so an artifact produced here would carry a hash "
            "nobody else could reproduce. Unset it, or set it to 1, and run again."
        )
    os.environ[OMP_ENV_VAR] = OMP_THREAD_PIN


def is_pinned() -> bool:
    """True when this process is already running under the pinned thread count."""
    return os.environ.get(OMP_ENV_VAR, "").strip() == OMP_THREAD_PIN


def main(argv: Sequence[str] | None = None) -> int:
    pin_openmp_threads()
    # Imported here, after the pin, and never at module scope.
    from touchline.modeling.train_boosting import main as train_main

    return train_main(argv)


if __name__ == "__main__":
    sys.exit(main())
