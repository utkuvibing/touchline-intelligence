/**
 * M0 landing page.
 *
 * M0 proves the pipeline (data -> database -> API -> UI -> deployment) and deliberately makes no
 * model claims. This page states that in plain language, because the deployment is public from the
 * first milestone and a visitor must not mistake a placeholder for a result.
 *
 * WP0.5 replaces the body with a raw shot map. The notice stays until a milestone has actually
 * earned the right to remove it.
 */

export const PROVISIONAL_NOTICE =
  "This is an early build. It does not yet contain a shot-quality model, and no performance " +
  "claim on this site has been evaluated.";

export default function Home() {
  return (
    <main>
      <h1>Touchline Intelligence Platform</h1>

      <p>
        Football research and decision-support built on StatsBomb Open Data — a relational dataset, a
        calibrated shot-quality model, and an analyst interface.
      </p>

      <section aria-labelledby="status-heading">
        <h2 id="status-heading">Current status</h2>
        <p role="note">{PROVISIONAL_NOTICE}</p>
      </section>

      <footer>
        <p>
          Data provided by StatsBomb. See the repository for competition coverage and licence
          details.
        </p>
      </footer>
    </main>
  );
}
