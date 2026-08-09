"""Fresh-process synthetic canonical-CPU reproducibility probe."""

from __future__ import annotations

import json

import torch

from support.wp26_synthetic import wp26_rows
from touchline.modeling.metrics import canonical_metrics_json
from touchline.modeling.mlp import configure_deterministic_runtime
from touchline.modeling.train_mlp import run_protocol

configure_deterministic_runtime()
result = run_protocol(
    wp26_rows(), device=torch.device("cpu"), published_metrics_path=None, epochs=2
)
payload = {
    "metrics": canonical_metrics_json(result.mlp_oof.metrics).decode("utf-8"),
    "oof_predictions": [values.tolist() for values in result.mlp_oof.probabilities_by_fold],
    "histories": [
        [[item.train_loss, item.validation_loss] for item in history]
        for history in result.mlp_oof.histories
    ],
    "fold_parameter_digests": list(result.mlp_oof.parameter_digests),
    "final_parameter_digest": result.final_fit.parameter_digest,
    "selection": result.chains,
}
print(json.dumps(payload, sort_keys=True, allow_nan=False))
