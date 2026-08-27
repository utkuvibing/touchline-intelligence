"use client";

import { BaselineStrip } from "@/components/explore/BaselineStrip";
import { BoundaryNote } from "@/components/explore/BoundaryNote";
import { HistoricalWorkspace } from "@/components/explore/HistoricalWorkspace";
import { PredictionPlayground } from "@/components/explore/PredictionPlayground";
import { RecordedWorkspace } from "@/components/explore/RecordedWorkspace";
import { ErrorNotice } from "@/components/status-notice";
import type { ConversionRate, Shot } from "@/lib/api";
import {
  isPublicationGateClosed,
  type HistoricalShotCollection,
  type ModelApiErrorInfo,
  type ModelMetadata,
  type ModelMetrics,
} from "@/lib/model-api";
import type { ResourceState } from "@/lib/server-data";

export interface ExploreRouteProps {
  metadata: ResourceState<ModelMetadata>;
  metrics: ResourceState<ModelMetrics>;
  historical: ResourceState<HistoricalShotCollection>;
  /** Ungated `/shots` data: every recorded WC2022 shot plus the API's returned total. */
  recorded:
    | { status: "ready"; shots: Shot[]; total: number }
    | { status: "error"; error: ModelApiErrorInfo };
  baseline: ResourceState<ConversionRate>;
  provenanceError: ModelApiErrorInfo | null;
}

/**
 * Composition for the Explore route.
 *
 * Two independent data worlds share this page. Recorded source facts (`/shots`, `/baseline`)
 * are ungated and render whenever they load. Historical model predictions render only when
 * the publication gate reports open AND every artifact identity agrees; any doubt collapses
 * the model view into an honest boundary statement, never a partial blend.
 */
export function ExploreRoute({
  metadata,
  metrics,
  historical,
  recorded,
  baseline,
  provenanceError,
}: ExploreRouteProps) {
  const metadataReady = metadata.status === "ready";
  const metricsReady = metrics.status === "ready";

  // Fail closed: without verified metadata the interface treats publication as closed.
  const publicationState = metadataReady ? metadata.data.historical_publication_state : "closed";

  const contractMismatch =
    metadataReady &&
    metricsReady &&
    publicationState === "published" &&
    historical.status === "error" &&
    isPublicationGateClosed(historical.error);

  const showHistoricalRows =
    metadataReady &&
    metricsReady &&
    provenanceError === null &&
    !contractMismatch &&
    publicationState === "published" &&
    historical.status === "ready";

  const unverifiedIdentity = !metadataReady || !metricsReady;
  // Any of these means "we cannot honestly say what is publishable right now", which is a
  // different statement from a deliberately closed licensing gate.
  const identityDispute =
    unverifiedIdentity || contractMismatch || provenanceError !== null;

  return (
    <>
      {!showHistoricalRows && provenanceError !== null && (
        <div className="notice notice-error" role="alert">
          <strong>Model identities do not agree</strong>
          <span>{provenanceError.message}</span>
          <code>{provenanceError.code}</code>
        </div>
      )}

      {showHistoricalRows ? (
        <section data-workspace="historical">
          <HistoricalWorkspace collection={historical.data} />
        </section>
      ) : (
        <>
          {unverifiedIdentity && (
            <div className="section-head">
              <h2>The model surfaces are withheld</h2>
              <p className="section-lede">
                Historical rows can only be shown next to a verified release identity. Load{" "}
                <a href="/model">the model page</a> once identity checks pass again.
              </p>
            </div>
          )}

          {contractMismatch && (
            <div className="gate-block">
              <span className="chip chip-blocked">Contract mismatch</span>
              <p className="gate-message">
                The API describes historical publication as open but then refused the rows. That
                combination means the deployment disagrees with itself, so the workspace stays
                closed until the two ends of the contract match.
              </p>
            </div>
          )}

          <BoundaryNote variant={identityDispute ? "unavailable" : "closed"} />
        </>
      )}

      <div className="section-head explore-sub-head">
        <h2>The recorded tournament</h2>
        <p className="section-lede">
          World Cup 2022 shots exactly as recorded: who took them, where, what happened. These
          are source facts from the public descriptive API, ungated and untouched by any model.
        </p>
      </div>

      {baseline.status === "ready" ? (
        <BaselineStrip
          baseline={baseline.data}
          shownShots={recorded.status === "ready" ? recorded.shots.length : 0}
        />
      ) : (
        <ErrorNotice
          title="The recorded tournament summary could not be loaded"
          error={baseline.error}
        />
      )}

      {recorded.status === "ready" ? (
        <section data-workspace="recorded">
          <RecordedWorkspace shots={recorded.shots} total={recorded.total} />
        </section>
      ) : (
        <>
          <ErrorNotice title="The recorded shot list could not be loaded" error={recorded.error} />
          <p className="muted workspace-count">
            This is an API failure, not an empty tournament. The map stays hidden rather than
            showing a partial tournament as if it were whole.
          </p>
        </>
      )}

      <div className="section-head explore-sub-head">
        <h2>Ask the model about a hypothetical shot</h2>
        <p className="section-lede">
          Place a shot anywhere eligible shots exist, set its context, and the served release
          answers with the calibrated conversion probability it assigns to that input. Live
          inference, computed per request; nothing here reads stored historical predictions.
        </p>
      </div>

      {metadata.status === "ready" && provenanceError === null ? (
        <PredictionPlayground metadata={metadata.data} />
      ) : metadata.status === "ready" ? (
        <p className="muted playground-hint">
          The playground waits while the served artifacts disagree about their identity; a
          prediction with no verified home would be decoration. It returns as soon as the
          endpoints agree again.
        </p>
      ) : (
        <ErrorNotice title="Playground needs the served input contract" error={metadata.error} />
      )}
    </>
  );
}
