/**
 * The M0 page, as a synchronous presentational component.
 *
 * Split from `app/page.tsx` deliberately. The page is an async Server Component that fetches, and
 * async Server Components cannot be unit-tested (the bundled Next.js Vitest guide says so
 * directly). Keeping every rendering decision here means the parts that carry the project's claims
 * — the provisional notice, the attribution, the "not an estimate" wording — stay testable, while
 * the untestable shell does nothing but fetch and pass props down.
 */

import { ShotMap } from "@/components/ShotMap";
import { isGoal, isPlottable, type ConversionRate, type Shot } from "@/lib/api";

export const PROVISIONAL_NOTICE =
  "This is an early build. It does not yet contain a shot-quality model, and no performance " +
  "claim on this site has been evaluated.";

export interface HomeViewProps {
  shots: Shot[];
  /** The API's unpaged total. Anything it exceeds `shots.length` by must be disclosed, not hidden. */
  total: number;
  rate: ConversionRate | null;
  error: string | null;
}

export function HomeView({ shots, total, rate, error }: HomeViewProps) {
  const plottable = shots.filter(isPlottable);
  const unplottable = shots.length - plottable.length;
  const goals = shots.filter(isGoal).length;
  // The map claims to show the tournament. If it is showing less, it has to say so rather than
  // quietly presenting a page as the whole.
  const missing = Math.max(0, total - shots.length);

  return (
    <main>
      <h1>Touchline Intelligence Platform</h1>

      <p>
        Football research and decision-support built on StatsBomb Open Data — a
        relational dataset, a calibrated shot-quality model, and an analyst
        interface.
      </p>

      <section aria-labelledby="status-heading">
        <h2 id="status-heading">Current status</h2>
        <p role="note">{PROVISIONAL_NOTICE}</p>
      </section>

      <section aria-labelledby="map-heading">
        <h2 id="map-heading">Recorded shots — FIFA World Cup 2022</h2>

        {error ? (
          // Shown rather than swallowed: a blank pitch with no explanation reads as "no shots were
          // taken", which is a different claim from "the API could not be reached".
          <p role="alert">
            Could not load shots from the API: {error}. The map is empty because
            the data could not be fetched, not because no shots were taken.
          </p>
        ) : (
          <>
            <p>
              {shots.length} shots shown, {goals} of them goals.
              {unplottable > 0
                ? ` ${unplottable} shot(s) had no recorded location and cannot be plotted; they are excluded from the map but counted here.`
                : ""}
            </p>
            {missing > 0 && (
              <p role="status">
                Showing {shots.length} of {total} recorded shots — {missing}{" "}
                could not be retrieved, so this map is not the complete
                tournament.
              </p>
            )}
            <ShotMap shots={plottable} />
          </>
        )}
      </section>

      {rate && (
        <section aria-labelledby="rate-heading">
          <h2 id="rate-heading">Conversion rate</h2>
          <p>
            <strong>
              {(rate.conversion_rate * 100).toFixed(2)}% ({rate.goals} of{" "}
              {rate.shots})
            </strong>
          </p>
          <p>{rate.cohort}</p>
          <p role="note">{rate.caveat}</p>
        </section>
      )}

      <footer>
        <p>
          Data provided by StatsBomb. See the repository for competition
          coverage and licence details.
        </p>
      </footer>
    </main>
  );
}
