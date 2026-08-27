export default function Loading() {
  return (
    <main className="page loading-page site-shell">
      <p className="muted">Touchline Intelligence</p>
      <h1>Loading live model data…</h1>
      <p>
        The page reads the model API on every request, so the first paint waits for the real
        numbers rather than showing placeholders.
      </p>
    </main>
  );
}
