# ADR 0015: WP3.1 serving bundle and startup semantics

**Status:** accepted and implemented for WP3.1. The project author manually approved the review
gate for this iteration; no independent Sol review ran and no independent-review `PASS` is claimed.

**Date:** 2026-08-10

**Contract:** [WP3.1 API and inference contract](../serving/wp3_1-api-and-inference-contract.md)

## Context

WP2.8 qualified one content-hashed calibrated model release and explicitly recorded
`serving_status = "not_served"`. WP3.1 must turn that release into an online inference runtime
without copying the full experiment tree into the image, reconstructing provenance from unrelated
files, weakening the frozen preprocessing contract, or allowing a deterministically corrupted model
to coexist with a successfully started application.

The existing application has two operational behaviors that cannot remain implicit. It currently
has no model lifecycle, and `/ready` returns HTTP 200 even when its body says `degraded`. A model
runtime also creates two distinct identities: the qualified WP2.8 scientific release and the exact
minimal M3 serving bundle deployed around it. Both must remain identifiable.

The public row-level endpoint is restricted to WC2022, and the source review still leaves public
row-level redistribution unresolved. WC2022 is also the Platt calibration/adoption split, not the
final tournament holdout. Serving must preserve both boundaries explicitly.

## Decision

1. Create one immutable minimal serving bundle containing only a serving manifest, the canonical
   WP2.8 release manifest, selected model pickle, WP2.4 artifact manifest, WP2.7 calibration
   decision, and WP2.7 holdout metrics. Do not copy the complete `artifacts/` or experiment trees.
2. Use the fixed runtime path
   `/app/backend/model-release/exp-20260810-wp2_8-release`. Neither environment variables nor
   requests may select an arbitrary model path.
3. Give the serving manifest its own content digest, `serving_manifest_sha256`. Expose it on every
   successful model-aware response so the deployed M3 package is identifiable separately from the
   parent WP2.8 release-manifest content and file hashes.
4. Treat the WP2.8 release manifest as the scientific source of truth. The serving manifest records
   package membership and the exact source-release link; it does not recreate or supersede model,
   calibration, split, or evaluation provenance.
5. Before startup completes, verify the serving manifest, every bundled file hash, the WP2.8
   release identity, artifact manifest, trusted pickle type/schema, frozen scaler/vocabulary/feature
   order, calibration-decision identity and Platt state, and immutable metrics schema/count anchors.
   Initialize exactly one runtime only after all checks pass.
6. Fail application startup on missing material, hash mismatch, malformed or unsupported schema,
   artifact incompatibility, invalid frozen preprocessing, invalid calibration, or invalid evidence.
   These deterministic failures have no recoverable HTTP 503 path because the process must not
   advertise successful startup.
7. Keep `/health` as database- and model-independent process liveness. Intentionally change
   `/ready` from the current "HTTP 200 with a degraded body" behavior to HTTP 200 only when the
   database, schema, and model runtime are ready, and HTTP 503 for a genuine runtime readiness
   failure. This HTTP 200 → 503 change is part of WP3.1's operational contract, not an incidental
   implementation detail.
8. Preserve the frozen M2 categorical behavior exactly. Exact retained levels use retained columns,
   exact development-rare members use the rare column, and every other non-empty string uses the
   all-zero reference encoding. Frozen evidence does not prove the literal string `"rare"` is a
   reserved invalid external value, so it receives the same unseen-reference behavior rather than
   being rejected specially. Do not trim, case-fold, alias, or fuzzy-match.
9. Keep WC2022 historical rows labelled as calibration-data historical predictions. Euro2024 remains
   the one-time tournament holdout and the source of final evaluation metrics. Qualified metrics are
   curated from immutable WP2 evidence and never recomputed from PostgreSQL at request time.
10. Use deterministic total ordering for historical rows. State only conditional cross-request
    offset stability: it holds while the pinned, idempotently loaded WC2022 snapshot remains
    unchanged, and is not guaranteed across rebuilds, source revisions, manual mutations, or future
    releases.
11. Generate golden expected vectors, logits, and probabilities independently through the qualified
    WP2 preprocessing/inference path and canonical WP2.8 artifact/calibration evidence, freeze them
    with source hashes, and use that frozen oracle to test WP3.1. The new runtime must never generate
    its own expected values.
12. Keep row-level historical model output disabled by default while the existing StatsBomb/Hudl
    publication gate remains open. Controlled local acceptance may enable it; production may not do
    so without recorded current direction.

## Consequences

A worker either starts with one fully validated qualified model or does not start. There is no silent
fallback, per-request artifact loading, partially initialized model endpoint, or corruption disguised
as transient unavailability. Runtime provenance can identify both the parent scientific release and
the exact deployed bundle.

The image carries several small duplicated release files, but not the large generated artifact or
experiment trees. Hashes and an exact file allow-list make drift visible, while preserving all
original WP2.x artifacts unchanged.

Changing degraded readiness from HTTP 200 to 503 intentionally changes existing endpoint behavior
and tests. It makes the response status usable by deployment routing rather than requiring an
operator to parse a nominally successful body. Deterministic startup corruption still never reaches
that endpoint.

The unseen-category policy is less user-friendly for typographical mistakes—`"head"`, `"Head "`,
and `"rare"` all encode as unseen reference values—but it is the qualified M2 behavior. Improving
that policy requires a future versioned model/input contract rather than an API-layer normalization.

Offset pagination remains deterministic for one fixed database state but is not snapshot isolation
across separate requests. The source commit pin, WP1.3 idempotent reject-on-change ingestion, and
fixed WC2022 public scope justify the intended stable-snapshot assumption; the API does not claim
stability if that assumption is broken.

## Rejected alternatives

- Copy the full `artifacts/` or experiment trees into Docker: rejected as unnecessary and contrary
  to a minimal immutable serving package.
- Use only an environment-provided model path: rejected because it permits an unregistered artifact
  to replace the qualified release without a code/manifest change.
- Reconstruct provenance from the pickle and unrelated files at request time: rejected because the
  validated manifests already own release identity.
- Start degraded after deterministic hash or schema failure: rejected because known corruption is
  not a transient readiness condition.
- Return HTTP 200 from `/ready` while declaring `degraded`: superseded intentionally by the WP3.1
  HTTP 503 operational contract.
- Reject all unseen categories or specially reject `"rare"`: rejected because frozen M2
  preprocessing maps every unseen value to reference and contains no evidence that `"rare"` is an
  invalid external token.
- Generate golden expectations through the new runtime: rejected as circular testing that could
  reproduce the same M3 defect on both sides of the assertion.
- Claim unconditional cross-request offset stability: rejected because fixed ordering alone cannot
  prevent page movement when the underlying rows change.
- Publicly enable historical row-level probabilities before the source-terms gate closes: rejected
  because it would silently expand the live row-level output under an unresolved publication rule.
