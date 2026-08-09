"""Fresh-process strict MLP artifact reload and inference probe."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

from support.wp26_synthetic import wp26_rows
from touchline.modeling.mlp_artifact import infer_mlp, load_mlp_artifact

parser = argparse.ArgumentParser()
parser.add_argument("--weights", required=True)
parser.add_argument("--metadata", required=True)
parser.add_argument("--preprocessing-digest", required=True)
parser.add_argument("--device", choices=("cpu", "cuda"), required=True)
args = parser.parse_args()
device = torch.device("cuda:0" if args.device == "cuda" else "cpu")
artifact = load_mlp_artifact(
    Path(args.weights),
    Path(args.metadata),
    device=device,
    expected_preprocessing_digest=args.preprocessing_digest,
)
print(
    json.dumps(
        {
            "weights_sha256": artifact.weights_sha256,
            "parameter_digest": artifact.parameter_digest,
            "preprocessing_digest": artifact.preprocessing_digest,
            "probabilities": infer_mlp(artifact, wp26_rows()).tolist(),
        },
        sort_keys=True,
        allow_nan=False,
    )
)
