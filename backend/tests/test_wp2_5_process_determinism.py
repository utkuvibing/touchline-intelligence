"""D20: two fresh Python processes must produce the same estimator and bundle bytes.

Why this must be a subprocess test. The defect it guards against is a **process-level** property:
scikit-learn's histogram gradient booster serializes differently under different OpenMP thread
counts, and the thread count is read by the OpenMP runtime when it initialises. Calling
``fit_boosting`` twice inside one interpreter cannot see that — the runtime is already loaded and
both fits share it, so such a test passes whether or not the pin exists. Only a fresh process
exercises the real entry/import path, which is where ``touchline.boosting_bootstrap`` sets the pin
before scikit-learn is imported.

A fourth contract guards the other direction: the pin belongs to the launcher, so importing the
WP2.3 split code or the WP2.4 logistic code must neither fail nor mutate the environment, whatever
the operator set ``OMP_NUM_THREADS`` to.

Three contracts:

1. two fresh processes agree on the estimator SHA **and** the bundle SHA;
2. the pin demonstrably took effect through that import path — the child reports
   ``OMP_NUM_THREADS=1`` and a threadpool that reports one thread;
3. a process started under a different thread count fails loudly, before the estimator is usable,
   rather than quietly producing an artifact whose published hash nobody can reproduce.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "backend" / "src"

#: Runs in a *fresh* interpreter, pinning first and importing the trainer second, exactly as
#: ``python -m touchline.boosting_bootstrap`` does.
CHILD = """
# Import order mirrors `python -m touchline.boosting_bootstrap`: pin first, then import the
# trainer. Importing numpy first would load OpenBLAS under its own default thread count ahead of
# the pin -- precisely what this ordering exists to prevent, and what an earlier draft got wrong.
from touchline.boosting_bootstrap import pin_openmp_threads  # the official launcher's pin
pin_openmp_threads()
from touchline.modeling import train_boosting  # imported only after the pin, as main() does

import hashlib, json, os, pickle
import numpy as np
from threadpoolctl import threadpool_info
from touchline.modeling.artifact import BoostingBundle, boosting_artifact_schema_version
from touchline.modeling.boosting import BoostingParams, fit_boosting
from touchline.modeling.preprocessing import ShotRow, encode_rows, fit_scaler

BODIES = ("Right Foot", "Left Foot", "Head")
rng = np.random.default_rng(11)
rows = []
for fold in range(5):
    for i in range(80):
        y = 1 if i < 14 else 0
        rows.append(ShotRow(
            shot_id="p%d-%03d" % (fold, i), match_id=900 + fold, fold=fold,
            competition_id=43, season_id=3, y=y,
            distance_to_goal=float(7.0 + 14.0 * rng.random() - 2.0 * y),
            visible_goal_angle=float(0.4 * rng.random() + 0.15 * y),
            body_part_name=BODIES[i % 3],
            technique_name="Normal" if i % 4 else "Volley",
            play_pattern_name="Regular Play" if i % 3 else "From Corner",
            first_time=None, under_pressure=None))

vocab = train_boosting.build_vocabulary(rows)
scaler = fit_scaler(rows)
cols = vocab.column_names()
X, _ = encode_rows(rows, vocab, scaler)
y = np.asarray([r.y for r in rows], dtype=np.int_)
indices = tuple(range(len(cols)))
params = BoostingParams(learning_rate=0.03, max_leaf_nodes=7, min_samples_leaf=20)
est = fit_boosting(X, y, params).estimator

bundle = BoostingBundle(
    schema_version=boosting_artifact_schema_version, experiment_id="proc-determinism",
    artifact_candidate="hist_gbm", selection_incumbent="full_minus_presence",
    hyperparameters={k: float(v) for k, v in params.as_dict().items()},
    code_commit="c", reproduction_commit="c", data_source_commit="d",
    cohort_sql_sha256="0" * 64, assignments_sha256="0" * 64,
    input_config_sha256="0" * 64, uv_lock_sha256="0" * 64,
    estimator=est, scaler=scaler, vocabulary=vocab,
    all_columns=tuple(cols), selected_columns=tuple(cols), selected_indices=indices,
    reference_levels=dict(vocab.reference),
    rare_mapping={f: tuple(v) for f, v in vocab.rare_members.items()})

print(json.dumps({
    "estimator_sha": hashlib.sha256(pickle.dumps(est, protocol=5)).hexdigest(),
    "bundle_sha": hashlib.sha256(pickle.dumps(bundle, protocol=5)).hexdigest(),
    "omp_num_threads": os.environ.get("OMP_NUM_THREADS"),
    "threadpool_num_threads": sorted({e["num_threads"] for e in threadpool_info()}),
    "predictions_sha": hashlib.sha256(
        np.ascontiguousarray(bundle.predict_proba(rows[:40])).tobytes()).hexdigest(),
}))
"""


def _run_child(extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("OMP_NUM_THREADS", None)
    env["PYTHONPATH"] = str(SRC)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", CHILD],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
        check=False,
    )


def test_two_fresh_processes_produce_the_same_estimator_and_bundle_bytes() -> None:
    first, second = _run_child(), _run_child()
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    a = json.loads(first.stdout)
    b = json.loads(second.stdout)
    assert a["estimator_sha"] == b["estimator_sha"], "estimator bytes differ across processes"
    assert a["bundle_sha"] == b["bundle_sha"], "bundle bytes differ across processes"
    # Behaviour agreeing while bytes disagree is the exact failure mode that invalidated the first
    # WP2.5 full-cohort run, so predictions alone are not treated as sufficient here.
    assert a["predictions_sha"] == b["predictions_sha"]


def test_the_pin_took_effect_through_the_real_import_path() -> None:
    """Without this, the test above could pass merely because both processes shared a default."""
    result = _run_child()
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["omp_num_threads"] == "1"
    assert payload["threadpool_num_threads"] == [1], (
        "a loaded runtime reported more than one thread despite the process-start pin"
    )


def test_a_process_started_under_a_different_thread_count_fails_loudly() -> None:
    result = _run_child({"OMP_NUM_THREADS": "8"})
    assert result.returncode != 0, "launching under OMP_NUM_THREADS=8 must not be allowed"
    assert "ThreadPinError" in result.stderr
    assert "OMP_NUM_THREADS" in result.stderr


#: Imports the WP2.3 and WP2.4 modelling modules and reports the environment it observed. It must
#: not raise, and it must leave OMP_NUM_THREADS exactly as the operator set it.
UNAFFECTED_CHILD = """
import json, os
before = os.environ.get("OMP_NUM_THREADS")
import touchline.modeling.splits          # WP2.3
import touchline.modeling.train           # WP2.4
import touchline.modeling.logistic        # WP2.4
print(json.dumps({"before": before, "after": os.environ.get("OMP_NUM_THREADS")}))
"""


def test_importing_wp2_3_and_wp2_4_modules_neither_fails_nor_mutates_the_environment() -> None:
    """The pin belongs to the WP2.5 launcher, not to the modelling package.

    An earlier version pinned from ``touchline.modeling.__init__``, so importing the split code or
    the logistic trainer -- neither of which the thread count affects -- rewrote the process
    environment and raised if the operator had chosen a different value. Import should not do that.
    """
    for setting in ("8", "1", None):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC)
        if setting is None:
            env.pop("OMP_NUM_THREADS", None)
        else:
            env["OMP_NUM_THREADS"] = setting
        result = subprocess.run(
            [sys.executable, "-c", UNAFFECTED_CHILD],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(ROOT),
            check=False,
        )
        assert result.returncode == 0, f"OMP_NUM_THREADS={setting!r}: {result.stderr}"
        payload = json.loads(result.stdout)
        assert payload["before"] == setting
        assert payload["after"] == setting, (
            f"importing modelling modules mutated OMP_NUM_THREADS from {setting!r} to "
            f"{payload['after']!r}"
        )


def test_an_inherited_pin_of_one_is_accepted() -> None:
    """Re-running under an already-correct environment is the same environment, not a conflict."""
    result = _run_child({"OMP_NUM_THREADS": "1"})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["omp_num_threads"] == "1"
