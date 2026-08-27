import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PredictionPlayground } from "./PredictionPlayground";
import type { ModelMetadata } from "@/lib/model-api";

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
      body_part: {
        reference: "Right Foot",
        retained: ["Head", "Left Foot"],
        rare_members: ["Other"],
      },
      technique: {
        reference: "Normal",
        retained: ["Half Volley", "Volley"],
        rare_members: ["Backheel", "Lob"],
      },
      play_pattern: {
        reference: "Regular Play",
        retained: ["From Corner", "From Counter"],
        rare_members: ["Other"],
      },
    },
  },
};

function jsonOk(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200 });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("PredictionPlayground", () => {
  it("renders choices strictly from the served input contract, defaults to the reference level", () => {
    render(<PredictionPlayground metadata={metadata} />);

    const bodyPart = screen.getByLabelText("Hypothetical body part") as HTMLSelectElement;
    expect(bodyPart.value).toBe("Right Foot");
    expect(
      Array.from(bodyPart.options).map((option) => option.value).sort(),
    ).toEqual(["Head", "Left Foot", "Other", "Right Foot"]);

    const playPattern = screen.getByLabelText("Hypothetical play pattern") as HTMLSelectElement;
    expect(playPattern.value).toBe("Regular Play");
    // reference + 2 retained + 1 rare member, exactly what the served contract advertises
    expect(Array.from(playPattern.options)).toHaveLength(4);
    // Keyboard users get exact coordinate entry alongside the pointer pitch.
    expect(screen.getByLabelText("Hypothetical location X (0–120)")).toHaveValue(102);
    expect(screen.getByLabelText("Hypothetical location Y (0–80)")).toHaveValue(40);
  });

  it("posts the constructed shot and shows the calibrated probability after verifying the provenance echo", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonOk({
        ...provenance,
        calibrated_probability: 0.2743,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<PredictionPlayground metadata={metadata} />);

    fireEvent.change(screen.getByLabelText("Hypothetical location X (0–120)"), { target: { value: "94.5" } });
    fireEvent.change(screen.getByLabelText("Hypothetical body part"), { target: { value: "Head" } });

    fireEvent.click(screen.getByRole("button", { name: /calculate probability/i }));

    await waitFor(() =>
      expect(screen.getByText("27.4%")).toBeInTheDocument(),
    );
    expect(screen.getByText(/artifact identity verified/i)).toBeInTheDocument();

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/model/predict"),
      expect.objectContaining({ method: "POST" }),
    );
    const body = JSON.parse(String(fetchMock.mock.calls[0][1].body));
    expect(body).toEqual({
      location_x: 94.5,
      location_y: 40,
      body_part: "Head",
      technique: "Normal",
      play_pattern: "Regular Play",
    });
  });

  it("maps field-level validation issues to the inputs that caused them", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: "request_validation_error",
            message: "Request validation failed.",
            details: [
              { field: "location_x", code: "request_validation_error", message: "location_x must be inside [0.0, 120]" },
              { field: null, code: "request_validation_error", message: "Unrecognised field attached." },
            ],
          },
        }),
        { status: 422 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<PredictionPlayground metadata={metadata} />);
    fireEvent.click(screen.getByRole("button", { name: /calculate probability/i }));

    await waitFor(() =>
      expect(screen.getByText(/location_x must be inside/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/unrecognised field attached\./i)).toBeInTheDocument();
    // The failed number is never displayed.
    expect(screen.queryByText(/%$/)).not.toBeInTheDocument();
  });

  it("warns instead of showing a number when the prediction echoes a different artifact identity", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonOk({
        ...provenance,
        artifact_sha256: "different-artifact-hash",
        calibrated_probability: 0.9,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<PredictionPlayground metadata={metadata} />);
    fireEvent.click(screen.getByRole("button", { name: /calculate probability/i }));

    await waitFor(() =>
      expect(screen.getByText(/model provenance differs at artifact_sha256/i)).toBeInTheDocument(),
    );
    // The confident wrong number stays hidden.
    expect(screen.queryByText("90.0%")).not.toBeInTheDocument();
  });

  it("surfaces a plain failure for a network or server outage", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("socket hung up")));

    render(<PredictionPlayground metadata={metadata} />);
    fireEvent.click(screen.getByRole("button", { name: /calculate probability/i }));

    await waitFor(() => expect(screen.getByText(/network_error/)).toBeInTheDocument());
    expect(screen.getByText(/fix anything flagged above and submit again/i)).toBeInTheDocument();
  });
});
