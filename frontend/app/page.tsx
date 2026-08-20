import { AnalystView, type ResourceState } from "@/components/AnalystView";
import {
  asModelApiErrorInfo,
  assertProvenanceEqual,
  fetchAllHistoricalShots,
  fetchModelMetadata,
  fetchModelMetrics,
  type HistoricalShotCollection,
  type ModelMetadata,
  type ModelMetrics,
  type ModelApiErrorInfo,
} from "@/lib/model-api";

export const dynamic = "force-dynamic";

function resourceState<T>(result: PromiseSettledResult<T>): ResourceState<T> {
  if (result.status === "fulfilled") return { status: "ready", data: result.value };
  return { status: "error", error: asModelApiErrorInfo(result.reason) };
}

export default async function Home() {
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
  }

  return (
    <AnalystView
      metadata={metadata}
      metrics={metrics}
      historical={historical}
      provenanceError={provenanceError}
    />
  );
}
