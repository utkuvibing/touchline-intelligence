# Lightweight Experiment Tracking

The project will not run MLflow or a tracking server initially. Experiments remain traceable through versioned configuration, an append-only results index, saved plots, immutable model metadata, and reproducible commands.

## Directory structure

```text
experiments/
  README.md                    # commands and schema
  results.csv                  # one summary row per completed run
  shot_quality/
    exp-YYYYMMDD-short-name/
      config.yaml              # complete run configuration
      metrics.json             # machine-readable overall and slice metrics
      notes.md                 # hypothesis, observations, decision, limitations
      plots/                   # calibration, ROC/PR, residual and slice plots
      artifact-manifest.json   # paths/hashes, not necessarily large binaries
  action_value/
    exp-YYYYMMDD-short-name/
      ...
artifacts/
  models/<experiment-id>/      # generated model plus environment/metadata
  reports/<experiment-id>/     # generated outputs; large files may be ignored
```

Large model/data artifacts should not be committed by default. Their manifest records path, checksum, creation command, and storage/recreation instructions. Small plots, metrics, configs, and notes are versioned.

## Required experiment record

Every completed run records:

- experiment ID and UTC date/time;
- Git commit (or `dirty` plus an explicit diff note during exploration);
- dataset version: ingestion manifest ID and SQL query/file hash;
- population and exclusions;
- feature-set name and exact feature list;
- target definition and feature availability time;
- split strategy, group key, temporal cutoff, and fold definitions;
- model class and full configuration;
- dependency/environment reference and random seed;
- overall discrimination, calibration, Brier score, and log loss as applicable;
- segment metrics and uncertainty where relevant;
- calibration method/results, if used;
- artifact and plot locations/checksums;
- hypothesis, observations, decision, limitations, and next action.

## Workflow

1. Write the question and expected decision in `notes.md`; exploration without a decision target is labelled exploratory.
2. Copy the nearest config and assign a unique `exp-YYYYMMDD-short-name` ID.
3. Pin the dataset manifest/query hash, split, features, model config, and seed before the final run.
4. Run through one documented command, for example `make train-xg CONFIG=experiments/.../config.yaml` (exact command established in Phase 0).
5. Generate metrics and plots from the run rather than transcribing them manually.
6. Inspect warnings, sample predictions, calibration, and error slices.
7. Add one row to `results.csv`; never overwrite an old experiment to make a result look better.
8. Write a conclusion: adopt, reject, or inconclusive, with evidence.
9. Re-run the selected candidate from a clean checkout/environment before release.

## Results index columns

```text
experiment_id,date_utc,git_commit,dataset_id,query_hash,feature_set,
split_strategy,model,seed,primary_metric,primary_value,brier,log_loss,
calibration_summary,status,decision,notes_path
```

Additional detailed and slice metrics live in `metrics.json`; do not turn the CSV into an unmaintainable schema.

## Comparison rules

- Compare models on the same locked evaluation population and splits.
- Preserve the simple baseline in every comparison table.
- Do not select on the final temporal holdout repeatedly.
- Report calibration and proper scoring rules alongside discrimination.
- Treat reference-implementation disagreement as a result to investigate, not a failure to hide.
- Do not claim reproducibility until another clean run produces materially equivalent outputs within documented tolerances.

