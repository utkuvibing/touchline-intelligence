import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AnalystView } from "./AnalystView";
import type {
  HistoricalShot,
  ModelMetadata,
  ModelMetrics,
  ProvenanceIdentity,
} from "@/lib/model-api";
import type { ResourceState } from "./AnalystView";

const provenance: ProvenanceIdentity = {
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

const reliability = [
  { bin: 0, lower: 0, upper: 0.2, count: 1151, positive_count: 63, mean_prediction: 0.07, observed_rate: 0.055 },
  { bin: 1, lower: 0.2, upper: 0.4, count: 123, positive_count: 24, mean_prediction: 0.269, observed_rate: 0.195 },
  { bin: 2, lower: 0.4, upper: 0.6, count: 25, positive_count: 8, mean_prediction: 0.494, observed_rate: 0.32 },
  { bin: 3, lower: 0.6, upper: 0.8, count: 4, positive_count: 3, mean_prediction: 0.724, observed_rate: 0.75 },
  { bin: 4, lower: 0.8, upper: 1, count: 1, positive_count: 0, mean_prediction: 0.904, observed_rate: 0 },
];

const metrics: ModelMetrics = {
  ...provenance,
  evidence_source: {
    holdout_metrics_sha256: "holdout-hash",
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
    raw: { log_loss: 0.23, brier: 0.06, max_supported_calibration_deviation: 0.05 },
    calibrated: { log_loss: 0.22, brier: 0.06, max_supported_calibration_deviation: 0.04 },
    raw_anchor_reliability: reliability.map((row) => ({
      ...row,
      raw_mean_prediction: row.mean_prediction,
      calibrated_mean_prediction: row.mean_prediction,
    })),
  },
  tournament_holdout: {
    split: "UEFA Euro 2024",
    role: "one_time_tournament_holdout",
    shots: 1304,
    matches: 51,
    goals: 98,
    observed_prevalence: 98 / 1304,
    adopted_variant: "calibrated",
    proper_scoring: { log_loss: 0.243112806225, brier: 0.066029980705 },
    discrimination: { roc_auc: 0.744677970691, pr_auc: 0.223985679737 },
    uncertainty: {
      method: "match_clustered_paired_bootstrap",
      confidence_level: 0.95,
      repetitions: 2000,
      seed: 0,
      log_loss: { lower: 0.21, upper: 0.27 },
      brier: { lower: 0.05, upper: 0.08 },
    },
    reliability,
    raw_comparator: {
      proper_scoring: { log_loss: 0.239307508271, brier: 0.064707399225 },
      discrimination: { roc_auc: 0.744677970691, pr_auc: 0.223985679737 },
      calibrated_minus_raw: {
        log_loss: 0.003805297954,
        brier: 0.00132258148,
        log_loss_interval: { lower: 0.000095, upper: 0.0078 },
        brier_interval: { lower: -0.000013, upper: 0.0028 },
      },
    },
  },
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

const ready = <T,>(data: T): ResourceState<T> => ({ status: "ready", data });

function baseProps() {
  return {
    metadata: ready(metadata),
    metrics: ready(metrics),
    historical: {
      status: "error" as const,
      error: {
        code: "publication_gate_closed",
        message: "public historical model shots are not enabled",
        status: 403,
      },
    },
    provenanceError: null,
  };
}

describe("WP3.2 analyst view", () => {
  it("keeps the model boundary, evidence roles, attribution, and gate state visible", () => {
    render(<AnalystView {...baseProps()} />);

    expect(screen.getByRole("heading", { level: 1, name: /shot quality, made inspectable/i })).toBeInTheDocument();
    expect(screen.getByText(/not statsbomb's proprietary xg model/i)).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /one-time tournament holdout/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/publication_gate_closed/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/data provided by statsbomb/i)).toBeInTheDocument();
    expect(screen.getAllByText(/NOT CLEARED/i).length).toBeGreaterThan(0);
    expect(
      screen.getByRole("heading", { name: /historical shot map is not publicly enabled/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/production deployment \/ smoke/i)).toBeInTheDocument();
  });

  it("renders every holdout reliability sample size and the raw comparator direction", () => {
    render(<AnalystView {...baseProps()} />);

    const table = screen.getByRole("table", { name: /euro 2024 calibrated reliability bins/i });
    expect(within(table).getByText("1151")).toBeInTheDocument();
    expect(within(table).getByText("123")).toBeInTheDocument();
    expect(within(table).getByText("25")).toBeInTheDocument();
    expect(within(table).getAllByText("4").length).toBeGreaterThan(0);
    expect(within(table).getAllByText("1").length).toBeGreaterThan(0);
    expect(screen.getByText(/calibrated − raw log loss/i)).toBeInTheDocument();
    expect(screen.getByText(/\+0\.0038/)).toBeInTheDocument();
    expect(screen.getByText(/sparse bins are visible/i)).toBeInTheDocument();
  });

  it("keeps reliability SVG tooltips as single text nodes for hydration", () => {
    const { container } = render(<AnalystView {...baseProps()} />);

    const titles = container.querySelectorAll(".reliability-chart title");
    expect(titles).toHaveLength(reliability.length);
    titles.forEach((title) => expect(title.childNodes).toHaveLength(1));
  });

  it("filters the gated historical workspace with AND semantics and keeps keyboard selection available", async () => {
    const historical = {
      ...baseProps().historical,
      status: "ready" as const,
      data: {
        ...provenance,
        cohort: "FIFA World Cup 2022 eligible non-penalty shots" as const,
        split_role: "calibration_data_historical_predictions" as const,
        historical_prediction_caveat: "Historical WC2022 calibration-data caveat.",
        shots: [
          shot({ shot_id: "goal", outcome: "Goal", calibrated_probability: 0.5 }),
          shot({ shot_id: "miss", player: "Other Player", calibrated_probability: 0.05 }),
        ],
        total: 2,
        limit: 1000,
        offset: 0,
        page_count: 1,
      },
    };

    const { container } = render(
      <AnalystView {...baseProps()} historical={historical} />,
    );

    expect(screen.getByText(/showing 2 of 2 eligible non-penalty shots/)).toBeInTheDocument();
    expect(screen.getByLabelText("Keyboard shot selector")).toBeInTheDocument();
    expect(screen.getAllByText("Historical WC2022 calibration-data caveat.")).toHaveLength(2);
    expect(container.querySelectorAll('[data-marker="true"]')).toHaveLength(2);
    expect(container.querySelector('[data-outcome="goal"]')).toBeInTheDocument();
    expect(container.querySelector('[data-outcome="non-goal"]')).toBeInTheDocument();
    expect(container.querySelector('[data-selection-ring="true"]')).toBeInTheDocument();

    const selector = screen.getByLabelText("Keyboard shot selector");
    fireEvent.change(selector, { target: { value: "miss" } });
    const detail = screen.getByRole("complementary");
    expect(within(detail).getByText("Other Player")).toBeInTheDocument();
    expect(within(detail).getByText("5.0%")).toBeInTheDocument();
  });

  it("withholds a mixed view when provenance identities disagree", () => {
    render(
      <AnalystView
        {...baseProps()}
        provenanceError={{
          code: "provenance_mismatch",
          message: "model provenance differs at serving_manifest_sha256",
          status: null,
        }}
      />,
    );

    expect(screen.getByText(/model identities do not agree/i)).toBeInTheDocument();
    expect(screen.getByText(/historical workspace withheld/i)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /one-time tournament holdout/i })).not.toBeInTheDocument();
  });
});
