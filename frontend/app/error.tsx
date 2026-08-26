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
    <main className="analyst-page" aria-labelledby="application-error-heading">
      <section className="historical-section">
        <p className="eyebrow">APPLICATION ERROR</p>
        <h1 id="application-error-heading">The model evidence page could not be displayed</h1>
        <p className="gate-message">Please retry. No prediction or historical data was shown.</p>
        <button type="button" onClick={reset} className="filter-reset">
          Retry
        </button>
      </section>
    </main>
  );
}
