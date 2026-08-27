import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ExploreRoute, type ExploreRouteProps } from "./ExploreRoute";
import type { ConversionRate, Shot } from "@/lib/api";
import type {
  HistoricalShot,
  HistoricalShotCollection,
  ModelApiErrorInfo,
  ModelMetadata,
} from "@/lib/model-api";

const provenance = {
  model_version: "wp2.8-test-model",
  release_id: "exp-test-release",
  serving_manifest_sha256: "serving-hash",
  release_manifest_sha256: "release-content-hash",
  release_manifest_file_sha256: "release-file-hash",
  artifact_sha256: "artifact-hash",
  calibration_decision_sha256: "calibration-hash",
};

const metadata: ModelMetadata = {
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

function recordedShot(overrides: Partial<Shot> = {}): Shot {
  return {
    shot_id: "rec-1",
    match_id: 3850001,
    match_date: "2022-12-04",
    competition_stage: "Round of 16",
    team: "Fixture United",
    opponent: "Fixture Rovers",
    player: "Bea Striker",
    period: 2,
    minute: 55,
    second: 10,
    location_x: 110.5,
    location_y: 42.5,
    outcome: "Goal",
    shot_type: "Open Play",
    body_part: "Right Foot",
    technique: "Normal",
    ...overrides,
  };
}

const baseline: ConversionRate = {
  method: "descriptive-prevalence",
  conversion_rate: 0.125,
  shots: 1494,
  goals: 186,
  cohort: "FIFA World Cup 2022 eligible non-penalty shots",
  caveat: "The full descriptive caveat text.",
};

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

function probabilityShot(overrides: Partial<HistoricalShot> = {}): HistoricalShot {
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

function gateClosedError(): ModelApiErrorInfo {
  return {
    code: "publication_gate_closed",
    message: "public historical model shots are not enabled",
    status: 403,
  };
}

/** Metrics values are untouched by this route: only load status matters for identity gating. */
const readyMetrics = { status: "ready", data: {} };

function baseProps(overrides: Partial<ExploreRouteProps> = {}): ExploreRouteProps {
  return {
    metadata: { status: "ready", data: metadata },
    metrics: readyMetrics as ExploreRouteProps["metrics"],
    historical: { status: "error", error: gateClosedError() },
    recorded: {
      status: "ready",
      total: 1494,
      shots: [
        recordedShot(),
        recordedShot({
          shot_id: "rec-2",
          outcome: "Saved",
          minute: 61,
          body_part: "Left Foot",
        }),
        recordedShot({
          shot_id: "rec-3",
          player: null,
          outcome: "Saved",
          location_x: null,
          location_y: null,
          minute: null,
          body_part: null,
          technique: null,
          shot_type: null,
        }),
      ],
    },
    baseline: { status: "ready", data: baseline },
    provenanceError: null,
    ...overrides,
  };
}

describe("ExploreRoute while publication is closed", () => {
  it("shows the boundary as a secondary note and keeps the descriptive tournament visible", () => {
    render(<ExploreRoute {...baseProps()} />);

    expect(screen.getByText(/publication closed/i)).toBeInTheDocument();
    expect(screen.getByText(/recorded source facts only/i)).toBeInTheDocument();

    expect(screen.getByRole("heading", { name: /the recorded tournament/i })).toBeInTheDocument();
    expect(screen.getByText(/showing 3 of 1,494/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Choose a shot (keyboard)")).toBeInTheDocument();
  });

  it("renders recorded facts only: uniform markers, outcome encodings, and no probabilities", () => {
    const { container } = render(<ExploreRoute {...baseProps()} />);
    const scoped = container.querySelector('[data-workspace="recorded"]') as HTMLElement;

    expect(scoped.querySelectorAll('[data-marker="true"]').length).toBeGreaterThan(0);
    expect(scoped.querySelector('[data-outcome="goal"]')).toBeInTheDocument();
    expect(scoped.querySelector('[data-outcome="non-goal"]')).toBeInTheDocument();
    const probabilitySlots = scoped.querySelectorAll("[data-probability]");
    expect(probabilitySlots.length).toBeGreaterThan(0);
    probabilitySlots.forEach((node) => expect(node.getAttribute("data-probability")).toBe("unpublished"));
    // No result callout may exist while publication is closed and nothing has been predicted.
    expect(scoped.querySelectorAll(".probability-callout")).toHaveLength(0);
    expect(container.querySelectorAll(".probability-callout")).toHaveLength(0);
  });

  it("keeps a disclosed list entry and detail for a shot without coordinates or optional fields", () => {
    render(<ExploreRoute {...baseProps()} />);

    fireEvent.change(screen.getByLabelText("Outcome"), { target: { value: "Saved" } });

    const selector = screen.getByLabelText("Choose a shot (keyboard)");
    // Choose the row without coordinates through the keyboard path, exactly as an analyst would.
    fireEvent.change(selector, { target: { value: "rec-3" } });

    expect(within(selector).getByText(/player unattributed/i)).toBeInTheDocument();
    expect(within(selector).getByText(/time unavailable/i)).toBeInTheDocument();

    const detail = screen.getByRole("complementary");
    // Every optional field of this row is absent from the source record.
    expect(within(detail).getAllByText(/not recorded/i).length).toBeGreaterThanOrEqual(3);
    expect(within(detail).getByText(/no plotted location/i)).toBeInTheDocument();
    expect(screen.getByText(/appear only in the list/i)).toBeInTheDocument();
  });

  it("surfaces the descriptive summary with its caveat collapsed, not deleted", () => {
    render(<ExploreRoute {...baseProps()} />);

    const caveat = document.querySelector("details.baseline-caveat") as HTMLDetailsElement;
    expect(caveat).not.toBeNull();
    expect(caveat.open).toBe(false);
    expect(screen.getByText("Conversion rate")).toBeInTheDocument();
    expect(screen.getByText("12.5%")).toBeInTheDocument();
    fireEvent.click(screen.getByText(/why this is not a model number/i));
    expect(caveat.open).toBe(true);
    expect(within(caveat).getByText(/full descriptive caveat text/i)).toBeInTheDocument();
  });

  it("offers live prediction while the gated rows stay absent", () => {
    render(<ExploreRoute {...baseProps()} />);

    expect(
      screen.getByRole("heading", { name: /ask the model about a hypothetical shot/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Hypothetical location X (0–120)")).toHaveValue(102);
    expect(screen.getByLabelText("Hypothetical body part")).toHaveValue("Right Foot");
    expect(screen.getByRole("button", { name: /calculate probability/i })).toBeEnabled();
    expect(
      screen.queryByText(/Historical WC2022 calibration-data caveat\./i),
    ).not.toBeInTheDocument();
  });

  it("withholds returned historical rows whenever the API reports publication closed", () => {
    const rows = historicalCollection([probabilityShot({ shot_id: "withheld-row-id" })]);
    const closedMetadata: ModelMetadata = {
      ...metadata,
      historical_publication_state: "closed",
    };

    render(
      <ExploreRoute
        {...baseProps({
          metadata: { status: "ready", data: closedMetadata },
          historical: { status: "ready", data: rows },
        })}
      />,
    );

    expect(screen.getByText(/publication closed/i)).toBeInTheDocument();
    expect(screen.queryByText(/showing 1 of 1/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/withheld-row-id/i)).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("Historical WC2022 calibration-data caveat");
  });
});

describe("ExploreRoute when publication is open", () => {
  function publishedProps(shots: HistoricalShot[]): ExploreRouteProps {
    return baseProps({
      metadata: {
        status: "ready",
        data: { ...metadata, historical_publication_state: "published" },
      },
      historical: { status: "ready", data: historicalCollection(shots) },
    });
  }

  it("shows the full probability workspace with filters, keyboard selection, and caveats", () => {
    const { container } = render(
      <ExploreRoute
        {...publishedProps([
          probabilityShot({ shot_id: "goal-id", outcome: "Goal", calibrated_probability: 0.5 }),
          probabilityShot({ shot_id: "miss-id", player: "Other Player", calibrated_probability: 0.05 }),
        ])}
      />,
    );
    const historical = container.querySelector('[data-workspace="historical"]') as HTMLElement;

    expect(within(historical).getAllByText(/Historical WC2022 calibration-data caveat\./i)).toHaveLength(2);
    expect(within(historical).getByText(/showing 2 of 2/i)).toBeInTheDocument();
    expect(historical.querySelectorAll('[data-marker="true"]')).toHaveLength(2);
    expect(historical.querySelector('[data-outcome="goal"]')).toBeInTheDocument();
    expect(historical.querySelector('[data-outcome="non-goal"]')).toBeInTheDocument();
    expect(historical.querySelector('[data-selection-ring="true"]')).toBeInTheDocument();

    fireEvent.change(within(historical).getByLabelText("Player"), { target: { value: "Other Player" } });
    const detail = within(historical).getByRole("complementary");
    expect(within(detail).getByText("Other Player")).toBeInTheDocument();
    expect(within(detail).getByText("5.0%")).toBeInTheDocument();
  });

  it("keeps the playground beside the open workspace without mixing the datasets", () => {
    render(<ExploreRoute {...publishedProps([probabilityShot()])} />);

    expect(screen.getByText(/showing 1 of 1/i)).toBeInTheDocument();
    expect(screen.queryByText(/publication closed/i)).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /ask the model about a hypothetical shot/i }),
    ).toBeInTheDocument();
  });

  it("reports a contract mismatch when the API claims open publication but refuses rows", () => {
    render(
      <ExploreRoute
        {...baseProps({
          metadata: {
            status: "ready",
            data: { ...metadata, historical_publication_state: "published" },
          },
          historical: { status: "error", error: gateClosedError() },
        })}
      />,
    );

    expect(screen.getByText(/contract mismatch/i)).toBeInTheDocument();
    // Recorded facts remain available even while the contract dispute is resolved.
    expect(screen.getByRole("heading", { name: /the recorded tournament/i })).toBeInTheDocument();
  });
});

describe("ExploreRoute under degraded conditions", () => {
  it("distinguishes an API failure from an empty tournament for the recorded list", () => {
    render(
      <ExploreRoute
        {...baseProps({
          recorded: {
            status: "error",
            error: { code: "http_503", message: "upstream down", status: 503 },
          },
        })}
      />,
    );

    expect(screen.getByText(/the recorded shot list could not be loaded/i)).toBeInTheDocument();
    expect(screen.getByText(/not an empty tournament/i)).toBeInTheDocument();
    expect(screen.queryByText(/showing 2 of 1,494/i)).not.toBeInTheDocument();
  });

  it("withholds the playground when metadata is missing rather than guessing the contract", () => {
    render(
      <ExploreRoute
        {...baseProps({
          metadata: {
            status: "error",
            error: { code: "http_503", message: "model api unreachable", status: 503 },
          },
          provenanceError: {
            code: "provenance_unverified",
            message: "identity unverified",
            status: null,
          },
        })}
      />,
    );

    expect(screen.queryByRole("button", { name: /calculate probability/i })).not.toBeInTheDocument();
    expect(screen.getByText(/playground needs the served input contract/i)).toBeInTheDocument();
    expect(screen.getByText(/probabilities unavailable/i)).toBeInTheDocument();
  });

  it("pauses the playground on a provenance disagreement instead of showing an unattributed number", () => {
    render(
      <ExploreRoute
        {...baseProps({
          provenanceError: {
            code: "provenance_mismatch",
            message: "model provenance differs at serving_manifest_sha256",
            status: null,
          },
        })}
      />,
    );

    expect(screen.getByText(/model identities do not agree/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /calculate probability/i })).not.toBeInTheDocument();
    expect(screen.getByText(/probabilities unavailable/i)).toBeInTheDocument();
    // Recorded facts are independent of the model identity dispute.
    expect(screen.getByRole("heading", { name: /the recorded tournament/i })).toBeInTheDocument();
  });
});
