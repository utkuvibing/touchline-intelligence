import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ModelApiError,
  ModelContractError,
  assertProvenanceEqual,
  fetchAllHistoricalShots,
  fetchHistoricalShotsPage,
  isPublicationGateClosed,
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
) {
  return {
    ...identity,
    cohort: "FIFA World Cup 2022 eligible non-penalty shots",
    split_role: "calibration_data_historical_predictions",
    historical_prediction_caveat: "These are calibration-data historical predictions.",
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
    expect(fetchMock).toHaveBeenCalledTimes(2);
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
