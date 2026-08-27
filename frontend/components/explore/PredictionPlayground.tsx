"use client";

import { useMemo, useState } from "react";

import { ShotPlacementPitch } from "@/components/explore/RecordedShotMap";
import {
  asModelApiErrorInfo,
  assertProvenanceEqual,
  ModelApiError,
  requestCalibratedProbability,
  type FieldIssue,
  type ModelApiErrorInfo,
  type ModelMetadata,
} from "@/lib/model-api";
import { formatProbability } from "@/lib/model-view";

type PlaygroundCategoryKey = "body_part" | "technique" | "play_pattern";

interface CategoryFieldView {
  key: PlaygroundCategoryKey;
  /** The served contract's supported levels: reference, retained, then the rare bucket. */
  choices: string[];
  value: string;
}

function buildFields(metadata: ModelMetadata): CategoryFieldView[] {
  const fields = metadata.input_contract.fields;
  return (["body_part", "technique", "play_pattern"] as const satisfies readonly PlaygroundCategoryKey[]).map((key) => {
    const field = fields[key];
    return {
      key,
      choices: [field.reference, ...field.retained, ...field.rare_members].sort((a, b) =>
        a.localeCompare(b),
      ),
      value: field.reference,
    };
  });
}

type PlaygroundPhase =
  | { kind: "idle" }
  | { kind: "submitting" }
  | { kind: "result"; probability: number }
  | { kind: "error"; error: ModelApiErrorInfo; issues: FieldIssue[] };

/**
 * Live single-shot inference against `/model/predict`, over the served input contract.
 *
 * This is not historical data: every answer is computed for the visitor's hypothetical shot at
 * request time. The response's artifact identity is verified against `/model` metadata before
 * the number is shown; a mismatch warns instead of displaying a confident wrong probability.
 */
export function PredictionPlayground({ metadata }: { metadata: ModelMetadata }) {
  const initial = useMemo(() => buildFields(metadata), [metadata]);
  const [locationX, setLocationX] = useState(102);
  const [locationY, setLocationY] = useState(40);
  const [fields, setFields] = useState<CategoryFieldView[]>(initial);
  const [phase, setPhase] = useState<PlaygroundPhase>({ kind: "idle" });

  const issueFor = (key: string) =>
    phase.kind === "error"
      ? phase.issues.find((issue) => issue.field === key)
      : undefined;

  function labelFor(key: PlaygroundCategoryKey): string {
    return `Hypothetical ${key.replace(/_/g, " ")}`;
  }

  const globalIssues =
    phase.kind === "error" ? phase.issues.filter((issue) => issue.field === null) : [];

  async function predict() {
    setPhase({ kind: "submitting" });
    try {
      const result = await requestCalibratedProbability({
        location_x: locationX,
        location_y: locationY,
        body_part: fields[0].value,
        technique: fields[1].value,
        play_pattern: fields[2].value,
      });
      // The echo must agree with the metadata this form was built from; otherwise the release
      // changed between page load and prediction and the number has no verified home.
      assertProvenanceEqual(metadata, result);
      setPhase({ kind: "result", probability: result.calibrated_probability });
    } catch (cause) {
      const info = asModelApiErrorInfo(cause);
      const details =
        cause instanceof ModelApiError ? (cause.details ?? []) : [];
      setPhase({ kind: "error", error: info, issues: details });
    }
  }

  function setChoice(key: string, value: string) {
    setFields((current) =>
      current.map((field) => (field.key === key ? { ...field, value } : field)),
    );
  }

  function clampCoordinate(value: string, min: number, max: number): number {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return min;
    return Math.min(max, Math.max(min, Math.round(parsed * 10) / 10));
  }

  return (
    <div className="playground-grid">
      <form
        className="playground-form"
        onSubmit={(event) => {
          event.preventDefault();
          void predict();
        }}
        aria-busy={phase.kind === "submitting"}
      >
        <fieldset className="playground-placement">
          <legend>Placement</legend>
          <div className="playground-pitch">
            <ShotPlacementPitch
              locationX={locationX}
              locationY={locationY}
              onPlace={(x, y) => {
                setLocationX(x);
                setLocationY(y);
                setPhase((current) => (current.kind === "error" ? { kind: "idle" } : current));
              }}
            />
          </div>
          <div className="playground-coordinates">
            <label className="filter-field">
              <span>Hypothetical location X (0–120)</span>
              <input
                type="number"
                name="location_x"
                value={locationX}
                min={0}
                max={120}
                step={0.1}
                aria-describedby={
                  issueFor("location_x") ? "playground-error-location_x" : undefined
                }
                onChange={(event) => setLocationX(clampCoordinate(event.target.value, 0, 120))}
              />
            </label>
            <label className="filter-field">
              <span>Hypothetical location Y (0–80)</span>
              <input
                type="number"
                name="location_y"
                value={locationY}
                min={0}
                max={80}
                step={0.1}
                aria-describedby={
                  issueFor("location_y") ? "playground-error-location_y" : undefined
                }
                onChange={(event) => setLocationY(clampCoordinate(event.target.value, 0, 80))}
              />
            </label>
          </div>
          {["location_x", "location_y"].map((key) => {
            const issue = issueFor(key);
            return issue ? (
              <p className="field-error" id={`playground-error-${key}`} key={key}>
                {issue.message}
              </p>
            ) : null;
          })}
        </fieldset>

        <fieldset className="playground-context">
          <legend>Recorded context</legend>
          {fields.map((field) => {
            const issue = issueFor(field.key);
            return (
              <label className="filter-field" key={field.key}>
                <span>{labelFor(field.key)}</span>
                <select
                  name={field.key}
                  value={field.value}
                  aria-describedby={issue ? `playground-error-${field.key}` : undefined}
                  onChange={(event) => {
                    setChoice(field.key, event.target.value);
                    setPhase((current) =>
                      current.kind === "error" ? { kind: "idle" } : current,
                    );
                  }}
                >
                  {field.choices.map((choice) => (
                    <option key={choice} value={choice}>
                      {choice}
                    </option>
                  ))}
                </select>
                {issue && (
                  <p className="field-error" id={`playground-error-${field.key}`}>
                    {issue.message}
                  </p>
                )}
              </label>
            );
          })}
        </fieldset>

        <button className="button button-primary" type="submit" disabled={phase.kind === "submitting"}>
          {phase.kind === "submitting" ? "Calculating…" : "Calculate probability"}
        </button>
      </form>

      <div className="playground-result">
        <div aria-live="polite">
          {phase.kind === "result" && (
            <>
              <p className="probability-callout playground-callout">
                <span>Calibrated conversion probability</span>
                <strong>{formatProbability(phase.probability)}</strong>
              </p>
              <p className="provenance-check">
                Artifact identity verified against the served release on this response
              </p>
            </>
          )}
          {phase.kind === "idle" && (
            <p className="muted playground-hint">
              Pick a spot, choose the context, then ask. The estimate answers &ldquo;shots like
              this&rdquo; under the released model, not what will actually happen next.
            </p>
          )}
          {phase.kind === "submitting" && (
            <p role="status" className="muted playground-hint">
              Calculating…
            </p>
          )}
          {phase.kind === "error" && (
            <>
              {globalIssues.length > 0 && (
                <ul className="notice notice-error playground-errors" role="alert">
                  {globalIssues.map((issue, index) => (
                    <li key={`${issue.code}-${index}`}>{issue.message}</li>
                  ))}
                </ul>
              )}
              <p className="notice notice-error playground-errors" role="alert">
                <strong>{phase.error.message}</strong>
                <code>{phase.error.code}</code>
              </p>
              <p className="muted playground-hint">
                Fix anything flagged above and submit again.
              </p>
            </>
          )}
        </div>
        <dl className="provenance-list playground-provenance">
          <div>
            <dt>Release</dt>
            <dd>{metadata.release_id}</dd>
          </div>
          <div>
            <dt>Model</dt>
            <dd>{metadata.model_version}</dd>
          </div>
          <div>
            <dt>Output</dt>
            <dd>Calibrated goal-conversion probability</dd>
          </div>
        </dl>
      </div>
    </div>
  );
}
