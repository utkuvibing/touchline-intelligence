"""Fresh-process synthetic CUDA qualification probe used by the local gate."""

from __future__ import annotations

import json

import torch

from support.wp26_synthetic import wp26_rows
from touchline.modeling.metrics import canonical_metrics_json
from touchline.modeling.mlp import apply_ieee_fp32_policy
from touchline.modeling.train_mlp import run_protocol

torch.use_deterministic_algorithms(True, warn_only=False)
torch.backends.cudnn.benchmark = False
torch.backends.cudnn.deterministic = True
apply_ieee_fp32_policy()
result = run_protocol(
    wp26_rows(), device=torch.device("cuda:0"), published_metrics_path=None, epochs=2
)
payload = {
    "metrics_sha256_input": canonical_metrics_json(result.mlp_oof.metrics).decode("utf-8"),
    "fold_parameter_digests": list(result.mlp_oof.parameter_digests),
    "final_parameter_digest": result.final_fit.parameter_digest,
    "histories": [
        [[item.train_loss, item.validation_loss] for item in history]
        for history in result.mlp_oof.histories
    ],
}
print(json.dumps(payload, sort_keys=True, allow_nan=False))
