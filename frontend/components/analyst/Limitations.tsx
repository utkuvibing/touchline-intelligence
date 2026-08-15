export function Limitations() {
  return (
    <section className="limitations-section" aria-labelledby="limitations-heading">
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">READ BEFORE USING THE NUMBER</p>
          <h2 id="limitations-heading">What this view does not claim</h2>
        </div>
      </div>
      <div className="limitation-grid">
        <article>
          <h3>Not StatsBomb xG</h3>
          <p>
            This is an independent Touchline model trained on the pinned event snapshot. It is not
            StatsBomb&apos;s proprietary expected-goals model and is not a provider benchmark.
          </p>
        </article>
        <article>
          <h3>Historical rows are calibration data</h3>
          <p>
            The historical probability map, when locally enabled, uses FIFA World Cup 2022 rows
            that helped fit and adopt the Platt transform. They are not untouched final-holdout
            predictions.
          </p>
        </article>
        <article>
          <h3>Holdout context matters</h3>
          <p>
            UEFA Euro 2024 is a one-time tournament holdout. Its date and tournament composition
            change together, so this is not a clean claim about football changing over time.
          </p>
        </article>
        <article>
          <h3>Small bins stay small</h3>
          <p>
            The reliability table shows every bin and its sample size. High-probability bins with
            very few shots should not be treated as stable evidence.
          </p>
        </article>
        <article>
          <h3>Event data is not tracking</h3>
          <p>
            This view uses recorded event fields and engineered shot geometry. It does not contain
            continuous tracking data or silently reinterpret freeze frames as tracking.
          </p>
        </article>
        <article>
          <h3>No causal recommendation</h3>
          <p>
            A conversion probability describes a model output for an eligible shot. It does not
            establish causation, player quality, tactical value, or what a coach should do next.
          </p>
        </article>
      </div>
    </section>
  );
}
