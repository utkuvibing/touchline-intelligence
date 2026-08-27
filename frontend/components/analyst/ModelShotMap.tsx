import type { HistoricalShot } from "@/lib/model-api";
import {
  PITCH_LENGTH,
  PITCH_WIDTH,
  formatProbability,
  isGoalShot,
  probabilityToRadius,
} from "@/lib/model-view";

interface ModelShotMapProps {
  shots: HistoricalShot[];
  selectedShotId: string | null;
  onSelect: (shotId: string) => void;
}

const MAP_STYLE = { width: "100%", height: "auto" } as const;

function PitchMarkings() {
  const line = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 0.3,
    opacity: 0.45,
  };

  return (
    <g aria-hidden="true">
      {/* outer boundary and halfway line */}
      <rect x={0} y={0} width={PITCH_LENGTH} height={PITCH_WIDTH} {...line} />
      <line x1={60} y1={0} x2={60} y2={PITCH_WIDTH} {...line} />
      <circle cx={60} cy={40} r={10.5} {...line} />
      <circle cx={60} cy={40} r={0.35} fill="currentColor" opacity={0.45} />
      {/* penalty areas and six-yard boxes */}
      <rect x={0} y={18} width={18} height={44} {...line} />
      <rect x={0} y={30} width={6} height={20} {...line} />
      <rect x={102} y={18} width={18} height={44} {...line} />
      <rect x={114} y={30} width={6} height={20} {...line} />
      <circle cx={108} cy={40} r={0.35} fill="currentColor" opacity={0.45} />
      {/* goals */}
      <line x1={0} y1={36} x2={0} y2={44} stroke="currentColor" strokeWidth={0.9} />
      <line x1={120} y1={36} x2={120} y2={44} stroke="currentColor" strokeWidth={0.9} />
    </g>
  );
}

function describe(shot: HistoricalShot): string {
  const when = shot.minute === null ? "time unavailable" : `${shot.minute}'`;
  return `${when} ${shot.player}, ${shot.team} versus ${shot.opponent}, ${shot.outcome}, ${formatProbability(shot.calibrated_probability)} calibrated probability`;
}

function ProbabilityLegend() {
  const examples = [0.05, 0.2, 0.5];
  return (
    <div className="map-legend" aria-label="Shot map legend">
      <div className="legend-group">
        <span className="legend-label">Marker area = probability</span>
        <div className="probability-legend">
          {examples.map((probability) => (
            <span className="probability-example" key={probability}>
              <svg viewBox="0 0 7 7" aria-hidden="true">
                <circle
                  cx="3.5"
                  cy="3.5"
                  r={probabilityToRadius(probability)}
                  fill="currentColor"
                  opacity="0.8"
                />
              </svg>
              <span>{probability * 100}%</span>
            </span>
          ))}
        </div>
      </div>
      <div className="legend-group">
        <span className="legend-label">Recorded outcome</span>
        <span className="outcome-legend-item">
          <span className="marker-key" aria-hidden="true" /> non-goal (hollow)
        </span>
        <span className="outcome-legend-item">
          <span className="marker-key marker-key-filled" aria-hidden="true" /> goal (filled)
        </span>
      </div>
      <p className="legend-note">
        Marker area, not radius, carries probability. The accent ring marks the selected shot.
      </p>
    </div>
  );
}

export function ModelShotMap({ shots, selectedShotId, onSelect }: ModelShotMapProps) {
  const goals = shots.filter(isGoalShot);
  const others = shots.filter((shot) => !isGoalShot(shot));
  const selectedShot = shots.find((shot) => shot.shot_id === selectedShotId) ?? null;
  const orderedShots = [...others, ...goals].filter(
    (shot) => shot.shot_id !== selectedShotId,
  );
  if (selectedShot) orderedShots.push(selectedShot);

  return (
    <figure className="map-figure">
      <div className="map-frame">
        <svg
          viewBox={`0 0 ${PITCH_LENGTH} ${PITCH_WIDTH}`}
          role="img"
          aria-label={`Model shot map: ${shots.length} filtered historical shots on a full pitch, attacking towards the right. Use the shot selector below to choose a shot.`}
          style={MAP_STYLE}
        >
          <PitchMarkings />
          {orderedShots.map((shot) => {
            const radius = probabilityToRadius(shot.calibrated_probability);
            const selected = shot.shot_id === selectedShotId;
            const goal = isGoalShot(shot);
            return (
              <g key={shot.shot_id} data-shot-id={shot.shot_id} data-outcome={goal ? "goal" : "non-goal"}>
                <circle
                  cx={shot.location_x}
                  cy={shot.location_y}
                  r={radius}
                  fill={goal ? "currentColor" : "none"}
                  stroke="currentColor"
                  strokeWidth={goal ? 0.18 : 0.28}
                  strokeDasharray={goal ? undefined : "0.5 0.35"}
                  opacity={goal ? 0.9 : 0.65}
                  onClick={() => onSelect(shot.shot_id)}
                  data-marker="true"
                  data-selected={selected}
                  aria-hidden="true"
                >
                  <title>{describe(shot)}</title>
                </circle>
                {selected && (
                  <circle
                    cx={shot.location_x}
                    cy={shot.location_y}
                    r={radius + 0.75}
                    fill="none"
                    stroke="var(--accent)"
                    strokeWidth={0.35}
                    pointerEvents="none"
                    data-selection-ring="true"
                    aria-hidden="true"
                  />
                )}
              </g>
            );
          })}
        </svg>
      </div>
      <figcaption className="map-caption">
        <div className="map-caption-head">
          <span>Full pitch, attacking right · StatsBomb 120 × 80</span>
          <span>{shots.length} shown</span>
        </div>
        <p>
          World Cup 2022 rows that the calibration actually learned from, plotted in the
          model&apos;s own coordinate space.
        </p>
        <ProbabilityLegend />
      </figcaption>
    </figure>
  );
}
