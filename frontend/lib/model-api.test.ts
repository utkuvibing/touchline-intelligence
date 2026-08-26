import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ModelApiError,
  ModelContractError,
  assertProvenanceEqual,
  fetchAllHistoricalShots,
  fetchHistoricalShotsPage,
  isPublicationGateClosed,
  parseModelMetadata,
  parseModelMetrics,
  parseHistoricalShotsPage,
  type HistoricalShot,
  type ProvenanceIdentity,
} from "./model-api";

const provenance: ProvenanceIdentity = {
  model_version: "model",
  release_id: "release",
  serving_manifest_sha256: "serving",
  release_manifest_sha256: "release-content",
  release_manifest_file_sha256: "release-file",
  artifact_sha256: "artifact",
  calibration_decision_sha256: "calibration",
};

function metadataPayload() {
  return {
    ...provenance,
    serving_state: "serving",
    historical_publication_state: "closed",
    release_status: "m2_qualified",
    qualification_serving_status: "not_served",
    runtime_status: "ready",
    candidate: "full_minus_presence",
    estimator: "logistic_regression",
    calibration: "platt_sigmoid",
    adopted_variant: "calibrated",
    output: "goal_conversion_probability",
    scopes: {
      development: {
        competitions: ["FIFA World Cup 2018", "UEFA Euro 2020"],
        shots: 2872,
        matches: 115,
        role: "model_development",
      },
      calibration: {
        competition: "FIFA World Cup 2022",
        shots: 1430,
        matches: 64,
        role: "platt_calibration_and_adoption",
      },
      tournament_holdout: {
        competition: "UEFA Euro 2024",
        shots: 1304,
        matches: 51,
        role: "one_time_final_evaluation",
      },
    },
    input_contract: {
      coordinates: {
        system: "StatsBomb",
        location_x: { minimum: 0, maximum: 120 },
        location_y: { minimum: 0, maximum: 80 },
      },
      categorical_policy: "exact_frozen_vocabulary_with_unseen_as_reference",
      fields: {
        body_part: { reference: "Right Foot", retained: ["Left Foot"], rare_members: ["Other"] },
        technique: { reference: "Normal", retained: ["Volley"], rare_members: ["Other"] },
        play_pattern: {
          reference: "Regular Play",
          retained: ["From Corner"],
          rare_members: ["Other"],
        },
      },
    },
  };
}

function metricsPayload() {
  const reliability = {
    bin: 0,
    lower: 0,
    upper: 0.2,
    count: 10,
    positive_count: 1,
    mean_prediction: 0.1,
    observed_rate: 0.1,
  };
  const calibrationReliability = {
    ...reliability,
    raw_mean_prediction: 0.1,
    calibrated_mean_prediction: 0.1,
  };
  const scores = { log_loss: 0.2, brier: 0.05, max_supported_calibration_deviation: 0.02 };
  const discrimination = { roc_auc: 0.7, pr_auc: 0.2 };
  return {
    ...provenance,
    evidence_source: {
      holdout_metrics_sha256: "holdout",
      evidence_status: "qualified_m2_evidence",
      recomputed_at_request_time: false,
    },
    calibration_adoption: {
      split: "FIFA World Cup 2022",
      role: "calibration",
      shots: 1430,
      matches: 64,
      adopted_variant: "calibrated",
      supported_raw_anchor_bins: 1,
      raw: scores,
      calibrated: scores,
      raw_anchor_reliability: [calibrationReliability],
    },
    tournament_holdout: {
      split: "UEFA Euro 2024",
      role: "one_time_tournament_holdout",
      shots: 1304,
      matches: 51,
      goals: 98,
      observed_prevalence: 0.075,
      adopted_variant: "calibrated",
      proper_scoring: { log_loss: 0.21, brier: 0.06 },
      discrimination,
      uncertainty: {
        method: "match_clustered_paired_bootstrap",
        confidence_level: 0.95,
        repetitions: 2000,
        seed: 0,
        log_loss: { lower: 0.2, upper: 0.22 },
        brier: { lower: 0.05, upper: 0.07 },
      },
      reliability: [reliability],
      raw_comparator: {
        proper_scoring: { log_loss: 0.2, brier: 0.05 },
        discrimination,
        calibrated_minus_raw: {
          log_loss: 0.01,
          brier: 0.01,
          log_loss_interval: { lower: 0, upper: 0.02 },
          brier_interval: { lower: 0, upper: 0.02 },
        },
      },
    },
  };
}

function shot(id: string, probability = 0.1): HistoricalShot {
  return {
    shot_id: id,
    match_id: 1,
    match_date: "2022-11-20",
    competition_stage: "Group Stage",
    team: "A",
    opponent: "B",
    player: `Player ${id}`,
    period: 1,
    minute: 1,
    second: 2,
    location_x: 112,
    location_y: 40,
    outcome: "Saved",
    shot_type: "Open Play",
    body_part: "Right Foot",
    technique: "Normal",
    play_pattern: "Regular Play",
    calibrated_probability: probability,
  };
}

function page(
  shots: HistoricalShot[],
  total: number,
  offset: number,
  identity = provenance,
  limit = 2,
  historicalPredictionCaveat = "These are calibration-data historical predictions.",
) {
  return {
    ...identity,
    cohort: "FIFA World Cup 2022 eligible non-penalty shots",
    split_role: "calibration_data_historical_predictions",
    historical_prediction_caveat: historicalPredictionCaveat,
    shots,
    total,
    limit,
    offset,
  };
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

beforeEach(() => {
  vi.unstubAllGlobals();
});

describe("WP3.1 model API adapter", () => {
  it("parses valid metadata and metrics at the response seam", () => {
    expect(parseModelMetadata(metadataPayload()).candidate).toBe("full_minus_presence");
    expect(parseModelMetrics(metricsPayload()).tournament_holdout.reliability).toHaveLength(1);
  });

  it("rejects an unregistered operational publication state", () => {
    const malformed = structuredClone(metadataPayload()) as Record<string, unknown>;
    malformed.historical_publication_state = "paused";
    expect(() => parseModelMetadata(malformed)).toThrow(/historical_publication_state/);
  });

  it.each(["location_x", "location_y"] as const)(
    "rejects a non-object %s coordinate bound",
    (coordinateField) => {
      const malformed = structuredClone(metadataPayload()) as {
        input_contract: { coordinates: Record<string, unknown> };
      };
      malformed.input_contract.coordinates[coordinateField] = 0;
      expect(() => parseModelMetadata(malformed)).toThrow(new RegExp(coordinateField));
    },
  );

  it.each(["candidate", "estimator", "calibration", "output"] as const)(
    "rejects a non-registered %s literal",
    (field) => {
      const malformed = structuredClone(metadataPayload()) as Record<string, unknown>;
      malformed[field] = "unregistered_value";
      expect(() => parseModelMetadata(malformed)).toThrow(new RegExp(field));
    },
  );

  it("rejects malformed metrics values at the response seam", () => {
    const malformed = structuredClone(metricsPayload()) as {
      tournament_holdout: { uncertainty: { confidence_level: number } };
    };
    malformed.tournament_holdout.uncertainty.confidence_level = 1.01;
    expect(() => parseModelMetrics(malformed)).toThrow(/confidence_level/);
  });

  it("uses the returned total and verifies every page identity", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("offset=0")) {
        return Promise.resolve(jsonResponse(page([shot("one"), shot("two")], 3, 0)));
      }
      return Promise.resolve(jsonResponse(page([shot("three")], 3, 2)));
    });
    vi.stubGlobal("fetch", fetchMock);

    const collection = await fetchAllHistoricalShots(2);

    expect(collection.total).toBe(3);
    expect(collection.shots.map((row) => row.shot_id)).toEqual(["one", "two", "three"]);
    expect(collection.page_count).toBe(2);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain("offset=2");
  });

  it("preserves the pinned 1,430-row acceptance invariant as data, not a UI constant", async () => {
    const firstShots = Array.from({ length: 1000 }, (_, index) => shot(`shot-${index}`));
    const secondShots = Array.from({ length: 430 }, (_, index) => shot(`shot-${index + 1000}`));
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      return Promise.resolve(
        jsonResponse(
          url.endsWith("offset=0")
            ? page(firstShots, 1430, 0, provenance, 1000)
            : page(secondShots, 1430, 1000, provenance, 1000),
        ),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const collection = await fetchAllHistoricalShots();

    expect(collection.total).toBe(1430);
    expect(collection.shots).toHaveLength(1430);
    expect(collection.page_count).toBe(2);
    expect(collection.historical_prediction_caveat).toBe(
      "These are calibration-data historical predictions.",
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("rejects a page that exceeds its returned limit", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(jsonResponse(page([shot("one"), shot("two"), shot("three")], 3, 0))),
      ),
    );

    await expect(fetchAllHistoricalShots(2)).rejects.toThrow(/exceeds its returned limit/);
  });

  it("rejects a later page that exceeds its returned limit", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      return Promise.resolve(
        jsonResponse(
          url.endsWith("offset=0")
            ? page([shot("one"), shot("two")], 5, 0)
            : page([shot("three"), shot("four"), shot("five")], 5, 2),
        ),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchAllHistoricalShots(2)).rejects.toThrow(/exceeds its returned limit/);
  });

  it("rejects a later page whose historical caveat changes", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      return Promise.resolve(
        jsonResponse(
          url.endsWith("offset=0")
            ? page([shot("one"), shot("two")], 3, 0)
            : page([shot("three")], 3, 2, provenance, 2, "A different caveat."),
        ),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchAllHistoricalShots(2)).rejects.toThrow(/changed its prediction caveat/);
  });

  it("rejects a duplicate or a short stalled page instead of presenting partial rows", async () => {
    const duplicateFetch = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      return Promise.resolve(
        jsonResponse(
          url.endsWith("offset=0")
            ? page([shot("one"), shot("two")], 3, 0)
            : page([shot("two")], 3, 2),
        ),
      );
    });
    vi.stubGlobal("fetch", duplicateFetch);
    await expect(fetchAllHistoricalShots(2)).rejects.toThrow(/repeated shot/);

    const stalledFetch = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      return Promise.resolve(
        jsonResponse(
          url.endsWith("offset=0")
            ? page([shot("one"), shot("two")], 4, 0)
            : page([shot("three")], 4, 2),
        ),
      );
    });
    vi.stubGlobal("fetch", stalledFetch);
    await expect(fetchAllHistoricalShots(2)).rejects.toThrow(/short page/);
  });

  it("surfaces the structured publication gate separately from an outage", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          jsonResponse(
            {
              error: {
                code: "publication_gate_closed",
                message: "public historical model shots are not enabled",
                details: [],
              },
            },
            403,
          ),
        ),
      ),
    );

    await expect(fetchHistoricalShotsPage()).rejects.toMatchObject({
      code: "publication_gate_closed",
      status: 403,
    } satisfies Partial<ModelApiError>);
    try {
      await fetchHistoricalShotsPage();
    } catch (cause) {
      expect(cause).toBeInstanceOf(ModelApiError);
      expect(isPublicationGateClosed((cause as ModelApiError).toInfo())).toBe(true);
    }
  });

  it.each([
    ["missing details", undefined],
    ["non-array details", "not-an-array"],
    [
      "non-empty details",
      [{ field: null, code: "publication_gate_closed", message: "unexpected detail" }],
    ],
  ])("does not classify a publication-gate envelope with %s as gate-closed", async (_label, details) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          jsonResponse(
            {
              error: {
                code: "publication_gate_closed",
                message: "public historical model shots are not enabled",
                details,
              },
            },
            403,
          ),
        ),
      ),
    );

    await expect(fetchHistoricalShotsPage()).rejects.toMatchObject({
      code: "http_403",
      status: 403,
    } satisfies Partial<ModelApiError>);
  });

  it.each([
    ["a non-object error", { error: "publication_gate_closed" }, 403],
    [
      "a non-string code",
      { error: { code: 403, message: "public historical model shots are not enabled", details: [] } },
      403,
    ],
    [
      "a non-string message",
      { error: { code: "publication_gate_closed", message: null, details: [] } },
      403,
    ],
    [
      "a non-object detail entry",
      {
        error: {
          code: "data_unavailable",
          message: "historical model shots are unavailable",
          details: ["invalid"],
        },
      },
      503,
    ],
    [
      "an invalid detail field",
      {
        error: {
          code: "data_unavailable",
          message: "historical model shots are unavailable",
          details: [{ field: 1, code: "invalid_filter", message: "invalid" }],
        },
      },
      503,
    ],
    [
      "an invalid detail code",
      {
        error: {
          code: "data_unavailable",
          message: "historical model shots are unavailable",
          details: [{ field: null, code: null, message: "invalid" }],
        },
      },
      503,
    ],
    [
      "an invalid detail message",
      {
        error: {
          code: "data_unavailable",
          message: "historical model shots are unavailable",
          details: [{ field: null, code: "invalid_filter", message: null }],
        },
      },
      503,
    ],
  ])("does not accept an envelope with %s", async (_label, body, status) => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(jsonResponse(body, status))));

    await expect(fetchHistoricalShotsPage()).rejects.toMatchObject({
      code: `http_${status}`,
      status,
    } satisfies Partial<ModelApiError>);
  });

  it("rejects non-finite or out-of-range probabilities at the response seam", () => {
    expect(() =>
      parseHistoricalShotsPage(
        page([shot("bad", Number.NaN)], 1, 0),
      ),
    ).toThrow(ModelContractError);
    expect(() =>
      parseHistoricalShotsPage(
        page([shot("bad", 1.01)], 1, 0),
      ),
    ).toThrow(/inside \[0, 1\]/);
  });

  it("names the exact provenance field that differs", () => {
    expect(() =>
      assertProvenanceEqual(provenance, {
        ...provenance,
        serving_manifest_sha256: "other",
      }),
    ).toThrow(/serving_manifest_sha256/);
  });
});
