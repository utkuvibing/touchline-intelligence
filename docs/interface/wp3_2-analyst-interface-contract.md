# WP3.2 analyst interface contract

**Status:** implementation in progress; local acceptance and independent review are not yet claimed.
**Depends on:** WP3.1 serving contract and ADR 0015.
**Scope:** frontend only. WP3.2 adds no backend endpoint and does not alter the WP3.1 API.

## 1. Product boundary

The page is a model-aware analyst view over the immutable WP3.1 serving contract. It presents:

- model identity and development/calibration/holdout roles;
- qualified Euro2024 holdout metrics and reliability evidence;
- a WC2022 historical probability workspace only when `/model/shots` is explicitly enabled; and
- limitations and visible StatsBomb attribution.

The view does not retrain, recalibrate, recompute evidence, access the Euro2024 database rows, call
`/model/predict` to reconstruct historical rows, or present the model as StatsBomb xG.

Three statuses remain independent:

| Status | WP3.2 meaning |
|---|---|
| Local implementation / acceptance | May become `PASS` only after the actual local evidence and review gates run. |
| Historical publication permission | `NOT CLEARED` until current written StatsBomb/Hudl direction resolves the existing source gate. |
| Production deployment / smoke | Not a WP3.2 claim; owned by WP3.3–WP3.4. |

## 2. Frozen data seam

The server page fetches these endpoints independently with `no-store` requests:

```text
GET /model
GET /model/metrics
GET /model/shots?limit=1000&offset=0
GET /model/shots?limit=1000&offset=1000
...
```

The historical request is made only through `/model/shots`. A `403 publication_gate_closed` is an
expected public state and is rendered as a publication-gate notice. The frontend never falls back to
legacy raw `/shots` rows for the model workspace and never makes one hypothetical `/model/predict`
request per historical row.

The first historical response's returned `total` is the UI source of truth. The value 1,430 is an
acceptance invariant for the pinned qualified snapshot, not a presentation constant. The client
pages until the returned total is satisfied, rejects empty/stalled/short pages before that total,
rejects duplicate `shot_id` values, and rejects a changed total, offset, or page size.

Offset stability has the WP3.1 condition: the pinned, idempotently loaded database snapshot must
remain unchanged between requests. No cross-request page stability is claimed across a rebuild,
source revision, or manual database mutation.

## 3. Provenance join key

Before rendering a combined model-aware view, `/model`, `/model/metrics`, and every successful
`/model/shots` page must agree byte-for-byte on all of these identity fields:

```text
model_version
release_id
serving_manifest_sha256
release_manifest_sha256
release_manifest_file_sha256
artifact_sha256
calibration_decision_sha256
```

A mismatch names the exact field and withholds the combined reliability or historical view. A
metadata/metrics outage also prevents historical rows from being combined because their identity
cannot be verified. Qualified metrics may render independently when their own response parses
successfully.

The adapter validates finite and bounded probabilities, reliability values, integer counts,
required literal split roles, required caveats, and the exact structured publication-gate error.
Malformed success payloads become visible frontend contract errors rather than empty data.

## 4. Historical workspace

When enabled locally, the workspace loads the complete bounded WC2022 response and derives exact
filter options client-side. Filters are:

```text
match_id, team, player, outcome, body_part, technique, play_pattern
```

They combine with `AND`, use exact values, and have no fuzzy matching, aliases, arbitrary sorting,
or URL persistence. The returned total remains visible beside the filtered count. The selected shot
survives a filter when possible; otherwise the first remaining shot is selected, and an empty result
has an explicit status message and empty detail panel.

The map keeps the StatsBomb 120 × 80 coordinate system and attacking direction. Probability is
encoded by circle area using exactly:

```text
r(p) = sqrt(r_min² + p × (r_max² − r_min²))
r_min = 0.45
r_max = 2.40
```

Since `πr(p)²` is affine in `p`, radius is not treated as probability. Goals are filled and
non-goals are hollow (with a stroke distinction that does not rely on color). A separate outer ring
means selection and carries no probability or outcome meaning. Coordinates are never jittered. A
single keyboard shot selector provides the keyboard path without putting every map marker in the tab
order.

The detail panel labels the calibrated probability and retains the API's WC2022 calibration-data
caveat beside recorded facts. It does not call recorded outcomes model inputs.

## 5. Reliability view

The primary chart is the calibrated variant on the one-time UEFA Euro 2024 tournament holdout.
The chart contains the diagonal and one unconnected point per non-null bin. The adjacent table keeps
every returned bin, count, positive count, range, mean prediction, and observed rate visible. Sparse
n=4 and n=1 bins are called out; no support threshold is invented.

WC2022 calibration/adoption metrics are shown in a separate section. The raw-vs-calibrated holdout
comparison is signed as calibrated minus raw. The page reports the observed positive differences in
Euro2024 log loss and Brier rather than implying that calibration must improve every holdout score.

## 6. Failure states

These states are distinct and visible:

- metadata/runtime unavailable;
- qualified metrics unavailable;
- historical publication gate closed;
- historical API/database failure;
- malformed or non-finite response payload;
- pagination shortfall, duplicate, changed total, or changed snapshot assumption; and
- provenance mismatch or unverified identity.

None is presented as “zero shots”.

## 7. Acceptance boundary

Local WP3.2 acceptance must cover the adapter/parser, provenance join key, returned-total paging,
exact filter semantics, probability-area formula, hollow/filled outcome encoding, separate selection
ring, reliable keyboard selection, sample-size visibility, truthful raw comparator, gate-closed
state, and responsive/manual inspection.

Production enablement of `/model/shots` remains forbidden while the publication gate is unresolved.
Deployment and deployed smoke evidence remain WP3.3–WP3.4.
