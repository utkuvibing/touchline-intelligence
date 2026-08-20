import type { HistoricalShot } from "@/lib/model-api";
import { formatProbability } from "@/lib/model-view";

interface ShotListProps {
  shots: HistoricalShot[];
  selectedShotId: string | null;
  onSelect: (shotId: string) => void;
}

function optionLabel(shot: HistoricalShot): string {
  const minute = shot.minute === null ? "time unavailable" : `${shot.minute}'`;
  return `${minute} · ${shot.player} · ${shot.team} · ${shot.outcome} · ${formatProbability(shot.calibrated_probability)}`;
}

export function ShotList({ shots, selectedShotId, onSelect }: ShotListProps) {
  return (
    <div className="shot-selector">
      <label htmlFor="shot-selector">Keyboard shot selector</label>
      <select
        id="shot-selector"
        value={selectedShotId ?? ""}
        onChange={(event) => onSelect(event.target.value)}
        disabled={shots.length === 0}
      >
        {shots.length === 0 ? (
          <option value="">No shots match these filters</option>
        ) : (
          shots.map((shot) => (
            <option key={shot.shot_id} value={shot.shot_id}>
              {optionLabel(shot)}
            </option>
          ))
        )}
      </select>
      <p className="muted">
        The map is pointer-selectable. This single selector provides the keyboard path without
        placing every marker in the tab order.
      </p>
    </div>
  );
}
