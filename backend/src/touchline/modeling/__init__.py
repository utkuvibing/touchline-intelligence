"""Model-development infrastructure.

WP2.3 holds the deterministic match-grouped split assignment; preprocessing, baselines, training,
evaluation and the serialized inference artifacts belong to WP2.4 and WP2.5.

**Importing this package pins OpenMP to a single thread (D20).** The pin lives here, and not in an
individual module, because it must take effect *before* the first import of a compiled dependency
that initialises an OpenMP runtime — scikit-learn above all. Python guarantees a package's
``__init__`` runs before any of its submodules, so this is the one location in the package whose
ordering cannot be rearranged by an import sorter or by which submodule a caller happens to reach
first.

Why it is needed: scikit-learn's ``HistGradientBoostingClassifier`` produces **byte-different
serialized models depending on the OpenMP thread count**, while its predictions are unchanged. That
was measured on the WP2.5 cohort: one thread and eight threads both give a 174,433-byte pickle with
bit-identical predictions, but different bytes. Since ``model_pickle_sha256`` is published as the
artifact's identity, the thread count has to be fixed for the process, not merely inside a
context manager around the fits.

``threadpoolctl.threadpool_limits(1)`` is kept in the training entry point as defence in depth. It
is not sufficient on its own: it constrains the runtime after it has loaded, whereas this pin is
read by the runtime when it initialises.
"""

from __future__ import annotations

import os

#: The only OpenMP thread count WP2.5 evidence may be produced under (D20).
OMP_THREAD_PIN = "1"

#: The environment variable the OpenMP runtime reads at initialisation.
OMP_ENV_VAR = "OMP_NUM_THREADS"


class ThreadPinError(RuntimeError):
    """The process was started under an OpenMP thread count that cannot reproduce the artifact."""


def pin_openmp_threads() -> None:
    """Fix ``OMP_NUM_THREADS`` at ``1`` for this process, or refuse to continue.

    An inherited value of exactly ``1`` is accepted — that is the same environment. Any other
    inherited value is a **loud failure**: silently overwriting it would run the estimator under an
    environment the operator did not ask for, and silently accepting it would produce an artifact
    whose published hash no one else can reproduce. Either way the operator must know, and they
    must know before the estimator is imported rather than after an hour of fitting.
    """
    inherited = os.environ.get(OMP_ENV_VAR)
    if inherited is not None and inherited.strip() != OMP_THREAD_PIN:
        raise ThreadPinError(
            f"{OMP_ENV_VAR} is set to {inherited!r}, but touchline.modeling requires "
            f"{OMP_THREAD_PIN!r}: scikit-learn's histogram gradient booster serializes differently "
            "under a different thread count, so an artifact produced here would carry a hash "
            "nobody else could reproduce. Unset it, or set it to 1, and run again."
        )
    os.environ[OMP_ENV_VAR] = OMP_THREAD_PIN


pin_openmp_threads()
