import Link from "next/link";

import { PitchGeometryFigure } from "@/components/pitch-geometry-figure";
import { HoldoutMetricGrid } from "@/components/holdout-metrics";
import { ErrorNotice } from "@/components/status-notice";
import {
  fetchModelMetadata,
  fetchModelMetrics,
  type ModelMetadata,
  type ModelMetrics,
} from "@/lib/model-api";
import { resourceState, type ResourceState } from "@/lib/server-data";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Shot quality from open event data",
};

const PIPELINE_STEPS = [
  {
    title: "Pinned source",
    body: "465 hashed StatsBomb event files at one fixed commit. Reproducibility starts with a source revision that cannot move.",
  },
  {
    title: "Validated storage",
    body: "Ordered migrations load the snapshot into normalized PostgreSQL. Missing optional values stay missing, and provider xG is excluded by a database constraint.",
  },
  {
    title: "Evaluated model",
    body: "Shot geometry and recorded context feed an L2-regularized logistic model. Gradient boosting and a small neural network got a fair run under the same locked protocol and did not beat it.",
  },
  {
    title: "Served release",
    body: "A content-hashed serving bundle runs behind FastAPI. This site reads it live and checks artifact identity across endpoints on every request.",
  },
] as const;

const BOUNDARIES = [
  {
    title: "No published row-level history",
    body: "Provider terms do not yet resolve publishing probabilities for individual historical shots, so the API refuses those rows outright. It substitutes and reconstructs nothing.",
  },
  {
    title: "Event data, not tracking",
    body: "The model reads recorded event fields and geometry derived from them. Shot freeze frames are event snapshots, not continuous tracking data, and are never treated as such.",
  },
  {
    title: "Probabilities, not prescriptions",
    body: "Each value is an estimate for a shot as recorded. It supports analysis; it does not establish cause, player quality, or the right next decision.",
  },
] as const;

function IdentityRows({ metadata }: { metadata: ModelMetadata }) {
  return (
    <dl className="identity-rows">
      <div>
        <dt>Estimator</dt>
        <dd>L2-regularized logistic regression on 16 engineered features</dd>
      </div>
      <div>
        <dt>Calibration</dt>
        <dd>Platt sigmoid, fitted and adopted on World Cup 2022 before the holdout was opened</dd>
      </div>
      <div>
        <dt>Final evaluation</dt>
        <dd>One-time Euro 2024 tournament holdout: {metadata.scopes.tournament_holdout.shots.toLocaleString("en-US")} shots</dd>
      </div>
      <div>
        <dt>Output</dt>
        <dd>Calibrated goal-conversion probability per eligible shot</dd>
      </div>
    </dl>
  );
}

function LiveFactStrip({
  metadata,
  metrics,
}: {
  metadata: ResourceState<ModelMetadata>;
  metrics: ResourceState<ModelMetrics>;
}) {
  if (metadata.status !== "ready") {
    return (
      <ErrorNotice
        title="Live model facts are unavailable right now"
        error={metadata.error}
      />
    );
  }

  const holdout = metadata.data.scopes.tournament_holdout;

  return (
    <div>
      <dl className="fact-strip">
        <div className="fact">
          <dt>Serving release</dt>
          <dd>
            <span className="mono">{metadata.data.release_id}</span>
          </dd>
        </div>
        <div className="fact">
          <dt>Runtime</dt>
          <dd>{metadata.data.serving_state === "serving" ? "Serving" : metadata.data.serving_state}</dd>
        </div>
        <div className="fact">
          <dt>Final holdout</dt>
          <dd>
            {holdout.competition} · {holdout.shots.toLocaleString("en-US")} shots
          </dd>
        </div>
        <div className="fact">
          <dt>Holdout log loss</dt>
          <dd>
            {metrics.status === "ready" ? (
              <span className="mono">{metrics.data.tournament_holdout.proper_scoring.log_loss.toFixed(3)}</span>
            ) : (
              "unavailable"
            )}
          </dd>
        </div>
      </dl>
      <p className="fact-note">
        Read from the model API on this request, not restated from a build-time snapshot.
      </p>
    </div>
  );
}

export default async function OverviewPage() {
  const [metadataResult, metricsResult] = await Promise.allSettled([
    fetchModelMetadata(),
    fetchModelMetrics(),
  ]);
  const metadata = resourceState(metadataResult);
  const metrics = resourceState(metricsResult);

  return (
    <main className="page">
      <section className="site-shell hero">
        <h1>Shot quality from open event data.</h1>
        <p className="hero-lede">
          An expected-goals model on pinned StatsBomb event data, evaluated under locked
          tournament splits and served with its evidence attached.
        </p>
        <div className="hero-actions">
          <Link href="/model" className="button button-primary">
            See the model evidence
          </Link>
          <Link href="/explore" className="button button-secondary">
            Explore the workspace
          </Link>
        </div>
      </section>

      <section className="site-shell" aria-label="Live model facts">
        <LiveFactStrip metadata={metadata} metrics={metrics} />
      </section>

      <section className="site-shell section">
        <div className="split">
          <div className="split-copy">
            <h2>A goal probability for every eligible shot.</h2>
            <p>
              The model estimates how likely a recorded, non-penalty shot is to become a goal. It
              was trained on a pinned StatsBomb Open Data snapshot: 230 matches, 843,050 recorded
              events, 5,606 modeled shots across four international tournaments.
            </p>
            <p>
              It is an independent Touchline Intelligence model, <strong>not StatsBomb&apos;s
              proprietary xG</strong>. The ingest strips provider xG before anything reaches
              storage, so it can never quietly become a feature.
            </p>
            {metadata.status === "ready" ? (
              <IdentityRows metadata={metadata.data} />
            ) : (
              <ErrorNotice title="Model identity is unavailable" error={metadata.error} />
            )}
          </div>
          <PitchGeometryFigure />
        </div>
      </section>

      <section className="site-shell section">
        <div className="section-head">
          <h2>From pinned snapshot to served probability</h2>
          <p className="section-lede">
            The model is the visible part. The lifecycle around it is what makes its numbers mean
            anything.
          </p>
        </div>
        <div className="pipeline">
          {PIPELINE_STEPS.map((step, index) => (
            <div className="pipeline-step" key={step.title}>
              <span className="pipeline-number" aria-hidden="true">
                {String(index + 1).padStart(2, "0")}
              </span>
              <h3>{step.title}</h3>
              <p>{step.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="site-shell section">
        <div className="section-head">
          <h2>The one-time holdout, reported as it landed</h2>
          <p className="section-lede">
            Euro 2024 was opened exactly once, after the model and its calibration were frozen.
            Both the raw and calibrated variants are reported, and neither was tuned afterwards.
          </p>
        </div>
        {metrics.status === "ready" ? (
          <HoldoutMetricGrid metrics={metrics.data} />
        ) : (
          <ErrorNotice title="Evaluation numbers are unavailable" error={metrics.error} />
        )}
        <div className="note-panel">
          <h3>The result nobody hid</h3>
          <p>
            Calibration was adopted on World Cup 2022, before Euro 2024 was ever opened. On the
            holdout, the calibrated variant then scored slightly worse than the raw one on both
            proper scores. The release ships calibration anyway: reversing the decision after
            seeing the holdout would have turned it into a second selection set.
          </p>
          <div className="note-stats">
            <Link href="/model">Full metrics, reliability bins, and the calibration decision</Link>
          </div>
        </div>
      </section>

      <section className="site-shell section">
        <div className="section-head">
          <h2>Boundaries, stated plainly</h2>
        </div>
        <div className="boundary-rows">
          {BOUNDARIES.map((boundary) => (
            <div key={boundary.title}>
              <h3>{boundary.title}</h3>
              <p>{boundary.body}</p>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
