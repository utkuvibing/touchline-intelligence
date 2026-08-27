import { ExploreRoute } from "@/components/explore/ExploreRoute";
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
import { fetchAllShots, fetchConversionRate, type ConversionRate, type Shot } from "@/lib/api";
import { resourceState } from "@/lib/server-data";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Explore World Cup 2022",
};

type RecordedState =
  | { status: "ready"; shots: Shot[]; total: number }
  | { status: "error"; error: ModelApiErrorInfo };

async function loadRecorded(): Promise<RecordedState> {
  try {
    // WC2022 is ~1.5k shots; the endpoint caps pages at 1000 rows and the client stops early
    // if the server ever does, so this is a bounded two-page request in practice.
    const all = await fetchAllShots();
    return { status: "ready", shots: all.shots, total: all.total };
  } catch (cause) {
    return { status: "error", error: asModelApiErrorInfo(cause) };
  }
}

export default async function ExplorePage() {
  const [metadataResult, metricsResult, historicalResult, recordedResult, baselineResult] =
    await Promise.allSettled([
      fetchModelMetadata(),
      fetchModelMetrics(),
      fetchAllHistoricalShots(),
      loadRecorded(),
      fetchConversionRate(),
    ]);

  const metadata = resourceState<ModelMetadata>(metadataResult);
  const metrics = resourceState<ModelMetrics>(metricsResult);
  const historical = resourceState<HistoricalShotCollection>(historicalResult);
  const recorded =
    recordedResult.status === "fulfilled"
      ? recordedResult.value
      : ({ status: "error", error: asModelApiErrorInfo(recordedResult.reason) } satisfies RecordedState);
  const baseline = resourceState<ConversionRate>(baselineResult);

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
        "Model identity and evaluation must both load before any model-derived view can be combined with them.",
      status: null,
    };
  }

  return (
    <main className="page">
      <section className="site-shell hero">
        <h1>World Cup 2022, shot by shot.</h1>
        <p className="hero-lede">
          Recorded shots you can filter and inspect, and the served model on call for
          hypotheticals. Where the publication boundary closes, the page says so instead of
          improvising.
        </p>
      </section>

      <section className="site-shell section section-first">
        <ExploreRoute
          metadata={metadata}
          metrics={metrics}
          historical={historical}
          recorded={recorded}
          baseline={baseline}
          provenanceError={provenanceError}
        />
      </section>
    </main>
  );
}
