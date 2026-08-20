import { describe, expect, it } from "vitest";

import {
  EMPTY_HISTORICAL_FILTERS,
  MAX_MARKER_RADIUS,
  MIN_MARKER_RADIUS,
  filterHistoricalShots,
  probabilityToRadius,
} from "./model-view";
import type { HistoricalShot } from "./model-api";

function shot(overrides: Partial<HistoricalShot> = {}): HistoricalShot {
  return {
    shot_id: "shot-1",
    match_id: 1,
    match_date: "2022-11-20",
    competition_stage: "Group Stage",
    team: "A",
    opponent: "B",
    player: "Player",
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
    calibrated_probability: 0.1,
    ...overrides,
  };
}

describe("historical model view calculations", () => {
  it("maps probability to the exact affine-area radius", () => {
    const low = probabilityToRadius(0);
    const middle = probabilityToRadius(0.5);
    const high = probabilityToRadius(1);

    expect(low).toBe(MIN_MARKER_RADIUS);
    expect(high).toBe(MAX_MARKER_RADIUS);
    expect(Math.PI * middle ** 2).toBeCloseTo(
      Math.PI * (MIN_MARKER_RADIUS ** 2 + 0.5 * (MAX_MARKER_RADIUS ** 2 - MIN_MARKER_RADIUS ** 2)),
      12,
    );
    expect(middle).toBeLessThan(high);
    expect(middle).toBeGreaterThan(low);
  });

  it.each([-0.01, 1.01, Number.NaN, Number.POSITIVE_INFINITY])(
    "rejects an invalid probability: %s",
    (probability) => {
      expect(() => probabilityToRadius(probability)).toThrow(/inside \[0, 1\]/);
    },
  );

  it("combines exact filters with AND semantics", () => {
    const shots = [
      shot({ shot_id: "one", team: "A", player: "P1", outcome: "Goal" }),
      shot({ shot_id: "two", team: "A", player: "P2", outcome: "Saved" }),
      shot({ shot_id: "three", team: "B", player: "P1", outcome: "Goal" }),
    ];

    expect(filterHistoricalShots(shots, { ...EMPTY_HISTORICAL_FILTERS, team: "A" })).toHaveLength(2);
    expect(
      filterHistoricalShots(shots, {
        ...EMPTY_HISTORICAL_FILTERS,
        team: "A",
        player: "P1",
        outcome: "Goal",
      }).map((row) => row.shot_id),
    ).toEqual(["one"]);
  });
});
