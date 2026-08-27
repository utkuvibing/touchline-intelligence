import type { ConversionRate } from "@/lib/api";

interface BaselineStripProps {
  baseline: ConversionRate;
  /**
   * How many shots the /shots workspace above actually lists (the API's returned total).
   * The baseline cohort is a subset of that: eligible non-penalty shots only, so the two
   * denominators differ by design and the difference is disclosed, never smoothed over.
   */
  recordedTotal?: number;
  /** Rows this page loaded, for the shortfall disclosure when paging ever stops early. */
  shownShots?: number;
}

/**
 * The tournament's descriptive rate, straight from `/baseline`.
 *
 * The API computes it over the same public World Cup 2022 scope as /shots, restricted to
 * eligible non-penalty shots with a known shot type, period and outcome. Its own cohort text
 * is shown verbatim because that denominator is the whole point of the number, and the API's
 * caveat is kept intact and collapsed: it exists to stop this prevalence being read as a
 * model output, but should not shout over the data.
 */
export function BaselineStrip({
  baseline,
  recordedTotal,
  shownShots,
}: BaselineStripProps) {
  const subset =
    recordedTotal !== undefined && baseline.shots < recordedTotal
      ? recordedTotal - baseline.shots
      : null;

  return (
    <div>
      <dl className="fact-strip">
        <div className="fact">
          <dt>Shots in cohort</dt>
          <dd>
            <span className="mono">{baseline.shots.toLocaleString("en-US")}</span>
          </dd>
        </div>
        <div className="fact">
          <dt>Goals in cohort</dt>
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
          <dt>Scope</dt>
          <dd>World Cup 2022, eligible non-penalty shots</dd>
        </div>
      </dl>
      <p className="fact-note">
        Read live from the public descriptive API; descriptive prevalence, meaning a summary of
        what happened rather than a model output.
        {shownShots !== undefined && shownShots < baseline.shots
          ? ` This page loaded ${shownShots.toLocaleString("en-US")} of them; the counts here cover the full cohort.`
          : ""}
      </p>
      {subset !== null && recordedTotal !== undefined && (
        <p className="fact-note">
          Two denominators, on purpose: the map above lists every recorded World Cup 2022 shot (
          {recordedTotal.toLocaleString("en-US")} total, including penalties and shootout kicks),
          while this rate covers only the eligible non-penalty subset defined by the cohort text
          above ({baseline.shots.toLocaleString("en-US")} shots, so{" "}
          {subset.toLocaleString("en-US")} recorded rows sit outside it).
        </p>
      )}
      <details className="baseline-caveat">
        <summary>Why this is not a model number</summary>
        <p>{baseline.caveat}</p>
      </details>
    </div>
  );
}
