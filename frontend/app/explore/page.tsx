import { ExploreView } from "@/components/ExploreView";
import { ErrorNotice } from "@/components/status-notice";
import {
  asModelApiErrorInfo,
  assertProvenanceEqual,
  fetchAllHistoricalShots,
  fetchModelMetadata,
  fetchModelMetrics,
  type HistoricalShotCollection,
  type ModelApiErrorInfo,
  type ModelMetadata,
  type ModelMetrics,
} from "@/lib/model-api";
import { resourceState } from "@/lib/server-data";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Explore the 2022 calibration set",
};

export default async function ExplorePage() {
  const [metadataResult, metricsResult, historicalResult] = await Promise.allSettled([
    fetchModelMetadata(),
    fetchModelMetrics(),
    fetchAllHistoricalShots(),
  ]);

  const metadata = resourceState<ModelMetadata>(metadataResult);
  const metrics = resourceState<ModelMetrics>(metricsResult);
  const historical = resourceState<HistoricalShotCollection>(historicalResult);

  let provenanceError: ModelApiErrorInfo | null = null;

  if (metadata.status === "ready" && metrics.status === "ready") {
    try {
      assertProvenanceEqual(metadata.data, metrics.data);
      if (historical.status === "ready") {
        assertProvenanceEqual(metadata.data, historical.data);
      }
    } catch (cause) {
      provenanceError = asModelApiErrorInfo(cause);
    }
  } else {
    provenanceError = {
      code: "provenance_unverified",
      message:
        "Model identity and evaluation must both load before historical rows can be combined with them.",
      status: null,
    };
  }

  const publicationState = metadata.status === "ready" ? metadata.data.historical_publication_state : "closed";

  return (
    <main className="page">
      <section className="site-shell hero">
        <h1>The 2022 calibration set, shot by shot.</h1>
        <p className="hero-lede">
          The released model&apos;s calibrated probability for each World Cup 2022 shot, subject
          to the publication boundary below.
        </p>
      </section>

      <section className="site-shell section section-first">
        {metadata.status !== "ready" ? (
          <ErrorNotice title="The workspace needs a verified model identity" error={metadata.error} />
        ) : metrics.status !== "ready" ? (
          <ErrorNotice title="The workspace needs a verified model identity" error={metrics.error} />
        ) : (
          <ExploreView
            historical={historical.status === "ready" ? historical.data : null}
            publicationState={publicationState}
            loadError={historical.status === "error" ? historical.error : null}
            provenanceError={provenanceError}
          />
        )}
      </section>
    </main>
  );
}
