"use client";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  // Keep the original error out of rendered UI while preserving Next's normal client diagnostics.
  void error;

  return (
    <main className="page loading-page site-shell">
      <p className="muted">Touchline Intelligence</p>
      <h1>This page could not be displayed</h1>
      <p>The model API may be unreachable. Nothing was shown partially or from memory.</p>
      <div>
        <button type="button" onClick={reset} className="button button-secondary">
          Retry
        </button>
      </div>
    </main>
  );
}
