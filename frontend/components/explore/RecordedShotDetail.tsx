import type { Shot } from "@/lib/api";

interface RecordedShotDetailProps {
  shot: Shot | null;
}

function value(value: string | number | null): string {
  return value === null || value === undefined ? "Not recorded" : String(value);
}

/**
 * Detail panel for recorded shots: source facts only.
 *
 * There is deliberately no probability callout here. This aside exists so a reader can tell,
 * per shot, what the record states versus what a model would claim — and where that claim
 * currently stands (unpublished).
 */
export function RecordedShotDetail({ shot }: RecordedShotDetailProps) {
  return (
    <aside className="detail-panel" aria-labelledby="recorded-shot-detail-heading">
      <div className="detail-head">
        <h2 id="recorded-shot-detail-heading">Recorded shot</h2>
        {shot && <span className="detail-id">{shot.shot_id.slice(0, 8)}</span>}
      </div>

      {!shot ? (
        <p className="empty-state">No shot matches the current filters.</p>
      ) : (
        <>
          <div className="recorded-outcome-callout">
            <span>Recorded outcome</span>
            <strong data-recorded-outcome={shot.outcome === "Goal" ? "goal" : "non-goal"}>
              {value(shot.outcome)}
            </strong>
          </div>
          <dl className="detail-grid">
            <div>
              <dt>Player</dt>
              <dd>{value(shot.player)}</dd>
            </div>
            <div>
              <dt>Minute</dt>
              <dd>{shot.minute === null ? "Not recorded" : `${shot.minute}'`}</dd>
            </div>
            <div>
              <dt>Team</dt>
              <dd>{shot.team}</dd>
            </div>
            <div>
              <dt>Opponent</dt>
              <dd>{shot.opponent}</dd>
            </div>
            <div>
              <dt>Match date</dt>
              <dd>{value(shot.match_date)}</dd>
            </div>
            <div>
              <dt>Stage</dt>
              <dd>{value(shot.competition_stage)}</dd>
            </div>
            <div>
              <dt>Period</dt>
              <dd>{value(shot.period)}</dd>
            </div>
            <div>
              <dt>Coordinates</dt>
              <dd className="mono">
                {shot.location_x !== null && shot.location_y !== null
                  ? `${shot.location_x.toFixed(1)}, ${shot.location_y.toFixed(1)}`
                  : "No plotted location"}
              </dd>
            </div>
            <div>
              <dt>Shot type</dt>
              <dd>{value(shot.shot_type)}</dd>
            </div>
            <div>
              <dt>Body part</dt>
              <dd>{value(shot.body_part)}</dd>
            </div>
            <div>
              <dt>Technique</dt>
              <dd>{value(shot.technique)}</dd>
            </div>
            <div>
              <dt>Model probability</dt>
              <dd data-probability="unpublished">
                Not published
                <span className="muted detail-note">behind the publication boundary</span>
              </dd>
            </div>
          </dl>
        </>
      )}
    </aside>
  );
}
