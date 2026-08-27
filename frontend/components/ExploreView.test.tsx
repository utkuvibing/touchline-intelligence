import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ExploreView } from "./ExploreView";
import type {
  HistoricalShot,
  ProvenanceIdentity,
  HistoricalShotCollection,
} from "@/lib/model-api";

const provenance: ProvenanceIdentity = {
  model_version: "wp2.8-test-model",
  release_id: "exp-test-release",
  serving_manifest_sha256: "serving-hash",
  release_manifest_sha256: "release-content-hash",
  release_manifest_file_sha256: "release-file-hash",
  artifact_sha256: "artifact-hash",
  calibration_decision_sha256: "calibration-hash",
};

function shot(overrides: Partial<HistoricalShot> = {}): HistoricalShot {
  return {
    shot_id: "shot-1",
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
    play_pattern: "Regular Play",
    calibrated_probability: 0.2,
    ...overrides,
  };
}

function historicalCollection(shots: HistoricalShot[]): HistoricalShotCollection {
  return {
    ...provenance,
    cohort: "FIFA World Cup 2022 eligible non-penalty shots",
    split_role: "calibration_data_historical_predictions",
    historical_prediction_caveat: "Historical WC2022 calibration-data caveat.",
    shots,
    total: shots.length,
    limit: 1000,
    offset: 0,
    page_count: 1,
  };
}

function publishedProps(shots: HistoricalShot[]) {
  return {
    historical: historicalCollection(shots),
    publicationState: "published" as const,
    loadError: null,
    provenanceError: null,
  };
}

describe("ExploreView", () => {
  it("keeps the calibration-set framing, caveats, and disclosure count visible", () => {
    render(
      <ExploreView
        {...publishedProps([
          shot({ shot_id: "goal", outcome: "Goal", calibrated_probability: 0.5 }),
          shot({ shot_id: "miss", player: "Other Player", calibrated_probability: 0.05 }),
        ])}
      />,
    );

    expect(screen.getAllByText(/Historical WC2022 calibration-data caveat\./)).toHaveLength(2);
    expect(screen.getByText(/showing 2 of 2/i)).toBeInTheDocument();
    expect(screen.getByText(/returned total is the source of truth/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Choose a shot (keyboard)")).toBeInTheDocument();
  });

  it("renders the map's probability, outcome, and selection encodings", () => {
    const { container } = render(
      <ExploreView
        {...publishedProps([
          shot({ shot_id: "goal", outcome: "Goal", calibrated_probability: 0.5 }),
          shot({ shot_id: "miss", player: "Other Player", calibrated_probability: 0.05 }),
        ])}
      />,
    );

    expect(container.querySelectorAll('[data-marker="true"]')).toHaveLength(2);
    expect(container.querySelector('[data-outcome="goal"]')).toBeInTheDocument();
    expect(container.querySelector('[data-outcome="non-goal"]')).toBeInTheDocument();
    expect(container.querySelector('[data-selection-ring="true"]')).toBeInTheDocument();
  });

  it("filters with AND semantics and moves keyboard selection into the detail panel", () => {
    render(
      <ExploreView
        {...publishedProps([
          shot({ shot_id: "goal", outcome: "Goal", calibrated_probability: 0.5 }),
          shot({ shot_id: "miss", player: "Other Player", calibrated_probability: 0.05 }),
        ])}
      />,
    );

    fireEvent.change(screen.getByLabelText("Player"), { target: { value: "Other Player" } });

    const detail = screen.getByRole("complementary");
    expect(within(detail).getByText("Other Player")).toBeInTheDocument();
    expect(within(detail).getByText("5.0%")).toBeInTheDocument();
    expect(within(detail).getAllByText(/Historical WC2022 calibration-data caveat\./)).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: /reset filters/i }));
    expect(
      screen.getByLabelText("Choose a shot (keyboard)"),
    ).toHaveValue("goal");
  });

  it("shows an empty-filter state rather than an empty map", () => {
    render(
      <ExploreView
        {...publishedProps([
          shot({ shot_id: "goal", outcome: "Goal" }),
          shot({ shot_id: "miss", player: "Other Player" }),
        ])}
      />,
    );

    fireEvent.change(screen.getByLabelText("Player"), { target: { value: "Other Player" } });
    fireEvent.change(screen.getByLabelText("Outcome"), { target: { value: "Goal" } });

    expect(screen.getByRole("status")).toHaveTextContent(/no shots match the current filters/i);
  });

  it("withholds returned rows when the API reports publication closed", () => {
    render(
      <ExploreView
        historical={historicalCollection([shot({ shot_id: "withheld" })])}
        publicationState="closed"
        loadError={null}
        provenanceError={null}
      />,
    );

    expect(screen.getByText(/publication closed/i)).toBeInTheDocument();
    expect(screen.queryByText(/showing 1 of 1/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/this row must stay withheld|withheld/i)).not.toBeInTheDocument();
  });

  it("reports a contract mismatch when the API claims open publication but refuses rows", () => {
    render(
      <ExploreView
        historical={null}
        publicationState="published"
        loadError={{
          code: "publication_gate_closed",
          message: "public historical model shots are not enabled",
          status: 403,
        }}
        provenanceError={null}
      />,
    );

    expect(screen.getByText(/contract mismatch/i)).toBeInTheDocument();
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  });

  it("surfaces provenance disagreements instead of a blended view", () => {
    render(
      <ExploreView
        historical={historicalCollection([shot()])}
        publicationState="published"
        loadError={null}
        provenanceError={{
          code: "provenance_mismatch",
          message: "model provenance differs at serving_manifest_sha256",
          status: null,
        }}
      />,
    );

    expect(screen.getByText(/model identities do not agree/i)).toBeInTheDocument();
    expect(screen.getByText(/publication closed/i)).toBeInTheDocument();
    expect(screen.queryByText(/showing 1 of 1/i)).not.toBeInTheDocument();
  });

  it("distinguishes an API failure from an empty cohort", () => {
    render(
      <ExploreView
        historical={null}
        publicationState="published"
        loadError={{ code: "http_503", message: "upstream unavailable", status: 503 }}
        provenanceError={null}
      />,
    );

    expect(screen.getByText(/shot rows could not be loaded/i)).toBeInTheDocument();
    expect(screen.getByText(/not an empty cohort/i)).toBeInTheDocument();
  });
});
