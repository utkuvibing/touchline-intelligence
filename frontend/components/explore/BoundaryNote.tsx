interface BoundaryNoteProps {
  /** Why historical probabilities are not on this page right now. */
  variant: "closed" | "unavailable";
}

/**
 * The publication boundary, stated once and quietly.
 *
 * This replaced the page-sized refusal the Explore route used to collapse into. The gate
 * itself is untouched: it lives in the API, and this note only explains what its current
 * state means for what the page shows.
 */
export function BoundaryNote({ variant }: BoundaryNoteProps) {
  return (
    <div className="boundary-note" data-testid="publication-boundary-note">
      {variant === "closed" ? (
        <>
          <span className="chip chip-blocked">Publication closed</span>
          <div className="boundary-note-body">
            <p>
              Historical row-level probabilities stay unpublished until StatsBomb and Hudl
              resolve the per-shot redistribution question in writing. Everything here therefore
              shows recorded source facts only. No marker, filter, or detail panel carries a
              model estimate.
            </p>
            <p className="muted">
              This is a licensing decision. The endpoint fails closed rather than approximating,
              and the playground below answers hypothetical shots through live inference instead.
            </p>
          </div>
        </>
      ) : (
        <>
          <span className="chip chip-blocked">Probabilities unavailable</span>
          <div className="boundary-note-body">
            <p>
              Historical model predictions are withheld because this deployment could not prove
              a single consistent release identity across its own endpoints. Recorded source
              facts below are unaffected by that dispute, so they stay visible.
            </p>
          </div>
        </>
      )}
    </div>
  );
}
