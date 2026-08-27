import { ReliabilityView } from "@/components/analyst/ReliabilityView";
import { ErrorNotice } from "@/components/status-notice";
import {
  assertProvenanceEqual,
  fetchModelMetadata,
  fetchModelMetrics,
  type ModelApiErrorInfo,
  type ModelMetadata,
  type ModelMetrics,
  type ProvenanceIdentity,
} from "@/lib/model-api";
import { resourceState } from "@/lib/server-data";
import { GITHUB_MODEL_CARD_URL } from "@/lib/site-links";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Model evidence",
};

function shortHash(value: string): string {
  return value.length > 14 ? `${value.slice(0, 14)}…` : value;
}

function ProvenanceList({ identity }: { identity: ProvenanceIdentity }) {
  const rows: Array<[string, string]> = [
    ["Model version", identity.model_version],
    ["Release ID", identity.release_id],
    ["Serving manifest", identity.serving_manifest_sha256],
    ["Release manifest (content)", identity.release_manifest_sha256],
    ["Release manifest (file)", identity.release_manifest_file_sha256],
    ["Model artifact", identity.artifact_sha256],
    ["Calibration decision", identity.calibration_decision_sha256],
  ];

  return (
    <div>
      <dl className="provenance-list">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>
              <span title={value}>{shortHash(value)}</span>
            </dd>
          </div>
        ))}
      </dl>
      <p className="provenance-check">Artifact identity agreed across both endpoints on this request</p>
    </div>
  );
}

function ScopeGrid({ metadata }: { metadata: ModelMetadata }) {
  const scopes = metadata.scopes;
  return (
    <dl className="scope-grid">
      <div>
        <dt>Development</dt>
        <dd>
          <strong>{scopes.development.shots.toLocaleString("en-US")}</strong>
          <span>
            shots · {scopes.development.matches} matches · feature and model selection
          </span>
        </dd>
      </div>
      <div>
        <dt>Calibration</dt>
        <dd>
          <strong>{scopes.calibration.shots.toLocaleString("en-US")}</strong>
          <span>
            shots · {scopes.calibration.matches} matches · Platt fit and adoption
          </span>
        </dd>
      </div>
      <div>
        <dt>Tournament holdout</dt>
        <dd>
          <strong>{scopes.tournament_holdout.shots.toLocaleString("en-US")}</strong>
          <span>
            shots · {scopes.tournament_holdout.matches} matches · opened exactly once
          </span>
        </dd>
      </div>
    </dl>
  );
}

function IdentitySection({ metadata }: { metadata: ModelMetadata }) {
  return (
    <section className="site-shell section section-first">
      <div className="section-head">
        <div className="section-head-row">
          <h2>What is being served</h2>
          <span className={`chip ${metadata.serving_state === "serving" ? "chip-serving" : "chip-blocked"}`}>
            {metadata.serving_state === "serving" ? "Serving" : metadata.serving_state}
          </span>
        </div>
        <p className="section-lede">
          A {metadata.estimator.replace(/_/g, " ")} with {metadata.calibration.replace(/_/g, " ")}{" "}
          calibration, fitted on development tournaments and adopted on World Cup 2022. This is an
          independent Touchline Intelligence estimate, not StatsBomb&apos;s proprietary xG model.
        </p>
      </div>

      <ScopeGrid metadata={metadata} />
      <ProvenanceList identity={metadata} />

      <p className="metric-footnote">
        Hashes are verified across the metadata and metrics endpoints on every request; a mismatch
        withholds the combined view below rather than mixing model identities. Hover a value for
        the full digest, or read the{" "}
        <a href={GITHUB_MODEL_CARD_URL} target="_blank" rel="noreferrer">
          full model card
        </a>
        .
      </p>
    </section>
  );
}

export default async function ModelPage() {
  const [metadataResult, metricsResult] = await Promise.allSettled([
    fetchModelMetadata(),
    fetchModelMetrics(),
  ]);
  const metadata = resourceState<ModelMetadata>(metadataResult);
  const metrics = resourceState<ModelMetrics>(metricsResult);

  let provenanceError: ModelApiErrorInfo | null = null;

  if (metadata.status === "ready" && metrics.status === "ready") {
    try {
      assertProvenanceEqual(metadata.data, metrics.data);
    } catch (cause) {
      provenanceError = {
        code: "provenance_mismatch",
        message: cause instanceof Error ? cause.message : "model provenance differs",
        status: null,
      };
    }
  }

  return (
    <main className="page">
      <section className="site-shell hero">
        <h1>Model evidence.</h1>
        <p className="hero-lede">
          The released estimator and its full evaluation, read live from the model API rather
          than restated from memory.
        </p>
      </section>

      {metadata.status === "ready" ? (
        <IdentitySection metadata={metadata.data} />
      ) : (
        <section className="site-shell section section-first">
          <ErrorNotice title="Model identity is unavailable" error={metadata.error} />
        </section>
      )}

      {metrics.status !== "ready" ? (
        <section className="site-shell section">
          <ErrorNotice title="Evaluation evidence is unavailable" error={metrics.error} />
        </section>
      ) : provenanceError ? (
        <section className="site-shell section">
          <div className="section-head">
            <h2>Evaluation withheld</h2>
            <p className="section-lede">
              The two endpoints disagree about which release is running. Showing one side&apos;s
              numbers next to the other&apos;s identity would produce a plausible-looking lie, so
              the evaluation stays hidden until the deployment is consistent again.
            </p>
          </div>
          <ErrorNotice title="Model identities do not agree" error={provenanceError} />
        </section>
      ) : (
        <section className="site-shell section">
          <ReliabilityView metrics={metrics.data} />
        </section>
      )}
    </main>
  );
}
