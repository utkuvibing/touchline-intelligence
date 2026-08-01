import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HomeView, PROVISIONAL_NOTICE } from "./HomeView";
import type { ConversionRate, Shot } from "@/lib/api";

function shot(overrides: Partial<Shot> = {}): Shot {
  return {
    shot_id: "s1",
    match_id: 900001,
    match_date: "2022-11-20",
    competition_stage: "Group Stage",
    team: "Fixture United",
    opponent: "Fixture Rovers",
    player: "Bea Striker",
    period: 1,
    minute: 23,
    second: 5,
    location_x: 112,
    location_y: 40,
    outcome: "Off T",
    shot_type: "Open Play",
    body_part: "Right Foot",
    technique: "Normal",
    ...overrides,
  };
}

const rate: ConversionRate = {
  method: "descriptive-prevalence",
  conversion_rate: 0.1063,
  shots: 1430,
  goals: 152,
  cohort: "Shots with a known shot type, period and outcome, excluding penalties.",
  caveat: "This is a descriptive summary, not a model and not a prediction.",
};

/**
 * These protect project rules, not rendering details. M0 is deployed publicly while it still has
 * no evaluated model, so the page must keep saying so — and must never present recorded outcomes
 * as an estimate of chance quality.
 */
describe("M0 landing page", () => {
  it("identifies the project", () => {
    render(<HomeView shots={[]} rate={null} error={null} />);

    expect(
      screen.getByRole("heading", { level: 1, name: /touchline intelligence platform/i }),
    ).toBeInTheDocument();
  });

  it("states that no evaluated model is present yet", () => {
    render(<HomeView shots={[]} rate={null} error={null} />);

    expect(screen.getByRole("note")).toHaveTextContent(PROVISIONAL_NOTICE);
  });

  it("attributes StatsBomb as the data source", () => {
    render(<HomeView shots={[]} rate={null} error={null} />);

    expect(screen.getByText(/data provided by statsbomb/i)).toBeInTheDocument();
  });

  it("renders one marker per plottable shot, goals distinguished from the rest", () => {
    const { container } = render(
      <HomeView
        shots={[
          shot({ shot_id: "a", outcome: "Goal" }),
          shot({ shot_id: "b", outcome: "Saved" }),
          shot({ shot_id: "c", outcome: "Off T" }),
        ]}
        rate={null}
        error={null}
      />,
    );

    // Pitch markings contribute one circle (the penalty spot); the rest are shots.
    const markers = container.querySelectorAll("svg circle");
    expect(markers.length).toBe(4);
    expect(screen.getByText(/3 shots shown, 1 of them goals/i)).toBeInTheDocument();
  });

  it("counts shots with no location instead of silently dropping them", () => {
    render(
      <HomeView
        shots={[shot({ shot_id: "a" }), shot({ shot_id: "b", location_x: null, location_y: null })]}
        rate={null}
        error={null}
      />,
    );

    expect(screen.getByText(/1 shot\(s\) had no recorded location/i)).toBeInTheDocument();
  });

  it("encodes nothing but the recorded outcome — every marker is the same size", () => {
    // Size-by-value and colour ramps are how expected-goals maps draw a model output. Using either
    // here would imply a chance-quality estimate that does not exist.
    const { container } = render(
      <HomeView
        shots={[shot({ shot_id: "a", outcome: "Goal" }), shot({ shot_id: "b", outcome: "Saved" })]}
        rate={null}
        error={null}
      />,
    );

    const radii = new Set(
      Array.from(container.querySelectorAll("svg circle[r]"))
        .map((c) => c.getAttribute("r"))
        .filter((r) => r !== "0.35"), // the penalty spot is a pitch marking, not a shot
    );
    expect(radii.size).toBe(1);
  });

  it("says a failed fetch is a failed fetch, not an absence of shots", () => {
    render(<HomeView shots={[]} rate={null} error="connect ECONNREFUSED" />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/could not load shots/i);
    expect(alert).toHaveTextContent(/not because no shots were taken/i);
  });

  it("publishes the conversion rate with its counts and caveat, never bare", () => {
    render(<HomeView shots={[]} rate={rate} error={null} />);

    const section = screen.getByRole("region", { name: /conversion rate/i });
    expect(within(section).getByText(/10\.63%/)).toBeInTheDocument();
    expect(within(section).getByText(/152 of 1430/)).toBeInTheDocument();
    expect(within(section).getByText(/not a model and not a prediction/i)).toBeInTheDocument();
  });
});
