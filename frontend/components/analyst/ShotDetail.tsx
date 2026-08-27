import type { HistoricalShot } from "@/lib/model-api";
import { formatProbability } from "@/lib/model-view";

interface ShotDetailProps {
  shot: HistoricalShot | null;
  historicalCaveat: string;
}

function value(value: string | number | null): string {
  return value === null ? "Not recorded" : String(value);
}

export function ShotDetail({ shot, historicalCaveat }: ShotDetailProps) {
  return (
    <aside className="detail-panel" aria-labelledby="shot-detail-heading">
      <div className="detail-head">
        <h2 id="shot-detail-heading">Shot detail</h2>
        {shot && <span className="detail-id">{shot.shot_id.slice(0, 8)}</span>}
      </div>

      {!shot ? (
        <p className="empty-state">No shot matches the current filters.</p>
      ) : (
        <>
          <div className="probability-callout">
            <span>Calibrated conversion probability</span>
            <strong>{formatProbability(shot.calibrated_probability)}</strong>
          </div>
          <dl className="detail-grid">
            <div>
              <dt>Player</dt>
              <dd>{shot.player}</dd>
            </div>
            <div>
              <dt>Recorded outcome</dt>
              <dd>{shot.outcome}</dd>
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
              <dt>Time</dt>
              <dd>
                {shot.minute === null
                  ? "Not recorded"
                  : `${shot.minute}:${String(shot.second ?? 0).padStart(2, "0")}`}
              </dd>
            </div>
            <div>
              <dt>Coordinates</dt>
              <dd className="mono">
                {shot.location_x.toFixed(1)}, {shot.location_y.toFixed(1)}
              </dd>
            </div>
            <div>
              <dt>Shot type</dt>
              <dd>{shot.shot_type}</dd>
            </div>
            <div>
              <dt>Body part</dt>
              <dd>{shot.body_part}</dd>
            </div>
            <div>
              <dt>Technique</dt>
              <dd>{shot.technique}</dd>
            </div>
            <div>
              <dt>Play pattern</dt>
              <dd>{shot.play_pattern}</dd>
            </div>
          </dl>
          <p className="caveat" role="note">
            {historicalCaveat}
          </p>
        </>
      )}
    </aside>
  );
}
