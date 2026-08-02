/**
 * Shown while the page's server-side fetch is in flight.
 *
 * The page is a dynamic Server Component that pages through every recorded shot before it can
 * render, so there is a real wait to describe. It says what is being waited for rather than
 * showing a bare spinner: "loading" and "loading 1,494 shots from the API" fail differently, and
 * only the second one tells a reader what to suspect when it never finishes.
 */

export default function Loading() {
  return (
    <main>
      <h1>Touchline Intelligence Platform</h1>
      <p role="status">Loading recorded shots from the API…</p>
    </main>
  );
}
