import type { ConversionRate } from "@/lib/api";

interface BaselineStripProps {
  baseline: ConversionRate;
  /** Shots the page received; may be fewer than `baseline.shots` only if paging ever stops early. */
  shownShots: number;
}

/**
 * The tournament's recorded headline numbers, straight from `/baseline`.
 *
 * The API's own caveat is kept intact and collapsed by default: it exists to stop this
 * prevalence being read as a model output, but should not shout over the data.
 */
export function BaselineStrip({ baseline, shownShots }: BaselineStripProps) {
  return (
    <div>
      <dl className="fact-strip">
        <div className="fact">
          <dt>Recorded shots</dt>
          <dd>
            <span className="mono">{baseline.shots.toLocaleString("en-US")}</span>
          </dd>
        </div>
        <div className="fact">
          <dt>Goals recorded</dt>
          <dd>
            <span className="mono">{baseline.goals.toLocaleString("en-US")}</span>
          </dd>
        </div>
        <div className="fact">
          <dt>Conversion rate</dt>
          <dd>
            <span className="mono">{(baseline.conversion_rate * 100).toFixed(1)}%</span>
          </dd>
        </div>
        <div className="fact">
          <dt>Cohort</dt>
          <dd>{baseline.cohort}</dd>
        </div>
      </dl>
      <p className="fact-note">
        Read live from the public descriptive API.{" "}
        {shownShots < baseline.shots
          ? `This page loaded ${shownShots.toLocaleString("en-US")} of them; the counts here cover the full cohort. `
          : ""}
        Descriptive prevalence, meaning a summary of what happened rather than a model output.
      </p>
      <details className="baseline-caveat">
        <summary>Why this is not a model number</summary>
        <p>{baseline.caveat}</p>
      </details>
    </div>
  );
}
