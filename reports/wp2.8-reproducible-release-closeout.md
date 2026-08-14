# WP2.8 reproducible calibrated-model release - closeout

**Closeout status:** PASS
**Release status:** `m2_qualified`
**Serving status:** `not_served`
**Independent reviewer:** GPT-5.6 Sol
**Independent verdict:** `PASS`

This closeout records the real WP2.8 acceptance run and the final gates. The acceptance command
was `uv run poe wp2-8-release`; it ran outside the ordinary `poe check` suite and published the
packet at the repository-relative path
`experiments/shot_quality/exp-20260810-wp2_8-release/`. The closeout did not rerun the release
command and did not regenerate or edit that packet.

## Acceptance result

The historical reproduction passed over the development scope only. The registered loader
materialized 2,872 shots from 115 matches in five development folds:

| Fold | 0 | 1 | 2 | 3 | 4 |
|---|---:|---:|---:|---:|---:|
| Shots | 570 | 552 | 602 | 576 | 572 |

`WC2022` and `Euro2024` rows were not loaded, preprocessed, scored, or passed to the historical
training process. `new_holdout_access = false` and `holdout_rows_loaded = false`.

The exact registered environment matched:

| Field | Value |
|---|---|
| OS / architecture | Windows / AMD64 |
| Python | CPython 3.12.11 |
| uv | 0.11.25 |
| `uv.lock` SHA-256 | `58c4b2b39cf78d217284784ada544633ea7c145a9a5a0a6c4eb6312eb7ea3902` |
| Reproduction commit | `81d4a56395985cb427fbcd13f38a0eb8c42e8be6` |
| Reproduction config SHA-256 | `30d34981d957f2b7c3832b2fe347f10986a6f14e58cca98a4abba673a56b0b0e` |

`exact_environment_match = true`, so exact comparison was required and passed:

- `byte_identical_reproduction_claim = true`;
- `artifact_byte_identical = true`;
- `canonical_json_equal = true`;
- regenerated model SHA-256: `9aeac9468c00bd1b93c771e454e48ca29e2eb759cf71836182a782d674bfadca`;
- regenerated metrics SHA-256: `00b8785b25c03758a93416b0edf461adf1584fc06b20be1f75ba702019a67e5c`;
- artifact-manifest SHA-256: `62cade6c3db5d741039de8f1ad53010319f422dcb942c96f16f1db8a498e8e79`.

The release references the exact merged WP2.7 base commit
`f48a1032f88afab968562c3ba3600618a2ed580a` and does not add API or UI serving. Serving remains an
M3 responsibility.

## Packet integrity

The published packet remained byte-for-byte unchanged during closeout. Its five file hashes are:

| Repository-relative packet file | SHA-256 |
|---|---|
| `experiments/shot_quality/exp-20260810-wp2_8-release/comparison.json` | `e7f9779cacd628e3cd622b0e2ac69963f373094ca1d6d8b386d2e99e9939850e` |
| `experiments/shot_quality/exp-20260810-wp2_8-release/config.json` | `09df31924f4b95fdb5ad4072c842e8c633ffc38aefc80e68a3f79f5f7368dd7c` |
| `experiments/shot_quality/exp-20260810-wp2_8-release/notes.md` | `05d4fe1541e18be4d60f7347177b777459db3175af0c76e41cc47cec8d6b3d22` |
| `experiments/shot_quality/exp-20260810-wp2_8-release/release-manifest.json` | `5c2e4016291c6ebe99ba69b37884f38791b4b6b1440c81107ed2a44db95645d4` |
| `experiments/shot_quality/exp-20260810-wp2_8-release/reproduction.json` | `b390d9c2cc7d4df865eb07517a84caf67a70c8b180751fc5607c045376c71fae` |

The manifest's recorded content digest is
`bad64e5972938335e62b98d694f24961117e5f46034518f38b61209e2c3ca87d`. It validates the frozen
WP2.4 artifact, metrics, configuration, and manifest, plus the WP2.7 decision, audit, measured
metrics, experiment record, membership digest, execution provenance, and their recorded SHA-256
values. Presentation-only reports, model cards, plots, and notes remain references and are not
integrity-critical release inputs.

The authoritative measured input hashes are:

- WP2.4 model: `9aeac9468c00bd1b93c771e454e48ca29e2eb759cf71836182a782d674bfadca`;
- WP2.4 metrics: `00b8785b25c03758a93416b0edf461adf1584fc06b20be1f75ba702019a67e5c`;
- WP2.4 artifact manifest: `62cade6c3db5d741039de8f1ad53010319f422dcb942c96f16f1db8a498e8e79`;
- WP2.4 resolved config: `b4e68bb0d2850770a9661fe19839a66695b328aafc9a9e58e40f5baab88eb394`;
- WP2.7 decision digest: `f5c9ccf665924069f755fbd669d4a9abada1e5791e957d3d436d42d500277e89`;
- WP2.7 decision file: `a88255ca56b478372ec76bc9dddb3295d9073a7f180d5dc8f0d9fa34bfd65d87`;
- WP2.7 holdout audit: `830d53c29b8d6bb5521995c5deab8d9f9cffa7997c2f2584ecfc3631f65c4939`;
- WP2.7 holdout metrics: `3443b4a5e19fd87b1ee599502152a7dcfe1af3d8466c09ad7cbf2bb8cae2e674`;
- WP2.7 experiment record: `6c3ede22ac846d59360676a32f4b16f0fbf0e31c832e5d962ca8a741cffbb40a`;
- WP2.7 membership digest: `6a4b02d6bfb9d3c4619239772c089a65455a5cb0299956912d2d520ca639b729`;
- WP2.7 execution provenance: `648d92dc99c34214505249dbe3e1533142b9bf79a7f817776dfbc2a8ba3c04ed`.

## Immutability and scope checks

- No WP2.4 measured evidence changed.
- No WP2.7 measured evidence changed.
- No row was added to `experiments/results.csv`.
- The existing WP2.8 packet was not regenerated or modified.
- The unrelated untracked `IDEA.md` was not modified or staged.

## Portability and harness incidents

The registered WP2.4 and WP2.8 lock digest is
`58c4b2b39cf78d217284784ada544633ea7c145a9a5a0a6c4eb6312eb7ea3902`. At the historical
reproduction commit, the raw Git blob had that SHA, while a Windows
`core.autocrlf=true` worktree produced the CRLF SHA
`f02faa7ea86d5808a8f210c0c8c2cda6781bdbb3a029bc8be0f87d032e95e71d`. The historical commit
predated the later `uv.lock text eol=lf` repository fix. The runner now uses a process-scoped
`core.autocrlf=false` for checkout and all historical Git commands, verifies the raw blob and
materialized bytes before `uv sync --locked`, and verifies a clean tracked worktree before
training. It does not modify persistent Git configuration and does not normalize arbitrary
historical files.

The first raw-blob correction exposed that rewriting `uv.lock` after checkout could itself trip
WP2.4's clean-tree provenance guard. The final fix makes the scoped checkout byte-correct at
materialization time and leaves the tracked file untouched when it already matches; a mismatch
fails closed rather than being hidden.

The mutation harness also encountered a transient Windows `[Errno 22] Invalid argument` while
restoring `backend/src/touchline/quality.py`. Restoration is now a dedicated small bounded retry
around the write/read operation, with exact byte verification and a loud failure after the bound.
The corrected WP2.7 source-identity anchor remains registered, and the harness leaves no mutation
behind or hides a permanent restoration failure.

## Final gates

| Gate | Result |
|---|---|
| Real WP2.8 historical reproduction | PASS |
| Exact environment match / byte-identical claim | `true` / `true` |
| `uv run poe check` | 1,069 passed, 122 skipped |
| Full mutation verification | 264 CAUGHT, 0 MISSED, 0 SKIP; all files restored |
| Independent final review | GPT-5.6 Sol - `PASS` |

The WP2.8 release is therefore qualified for M2 as a reproducible, content-hashed release packet;
it is not served by an API or UI.
