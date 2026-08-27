"use client";

import type { MouseEvent } from "react";

import { PITCH_VIEWBOX, PitchMarkings } from "@/components/analyst/Pitch";
import { isGoal, type PlottableShot } from "@/lib/api";

interface RecordedShotMapProps {
  shots: PlottableShot[];
  selectedShotId: string | null;
  onSelect: (shotId: string) => void;
}

const MAP_STYLE = { width: "100%", height: "auto" } as const;

/** Marker radius for recorded shots. Constant on purpose: nothing here has a probability to encode. */
const MARKER_RADIUS = 1.1;

function describe(shot: PlottableShot): string {
  const when = shot.minute === null ? "time unavailable" : `${shot.minute}'`;
  return `${when} ${shot.player ?? "player unattributed"}, ${shot.team} versus ${shot.opponent}, recorded outcome ${shot.outcome ?? "unrecorded"}`;
}

/**
 * The ungated shot map over `/shots` source facts.
 *
 * Encodings are deliberately the ones the data states as fact: position from the record,
 * fill from the recorded outcome, selection by interaction. Marker size never varies,
 * because this view carries no model output that could justify varying it.
 */
export function RecordedShotMap({ shots, selectedShotId, onSelect }: RecordedShotMapProps) {
  const goals = shots.filter(isGoal);
  const others = shots.filter((shot) => !isGoal(shot));
  const selectedShot = shots.find((shot) => shot.shot_id === selectedShotId) ?? null;
  const orderedShots = [...others, ...goals].filter(
    (shot) => shot.shot_id !== selectedShotId,
  );
  if (selectedShot) orderedShots.push(selectedShot);

  return (
    <figure className="map-figure">
      <div className="map-frame">
        <svg
          viewBox={PITCH_VIEWBOX}
          role="img"
          aria-label={`Recorded shot map: ${shots.length} World Cup 2022 shots with locations, attacking towards the right. Recorded outcomes only; no model probabilities are shown here. Use the shot selector below to choose a shot.`}
          style={MAP_STYLE}
        >
          <PitchMarkings />
          {orderedShots.map((shot) => {
            const selected = shot.shot_id === selectedShotId;
            const goal = isGoal(shot);
            return (
              <g
                key={shot.shot_id}
                data-shot-id={shot.shot_id}
                data-outcome={goal ? "goal" : "non-goal"}
              >
                <circle
                  cx={shot.location_x}
                  cy={shot.location_y}
                  r={MARKER_RADIUS}
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
                    r={MARKER_RADIUS + 0.75}
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
          <span>{shots.length} with a location</span>
        </div>
        <p>
          Recorded outcomes only, in the source coordinate space. Markers are one size because
          marker size would otherwise imply an estimate nobody made.
        </p>
        <div className="map-legend">
          <div className="legend-group">
            <span className="legend-label">Marker</span>
            <span className="outcome-legend-item">
              <span className="marker-key" aria-hidden="true" /> non-goal (hollow)
            </span>
            <span className="outcome-legend-item">
              <span className="marker-key marker-key-filled" aria-hidden="true" /> goal (filled)
            </span>
            <span className="outcome-legend-item">one size, always</span>
          </div>
          <div className="legend-group">
            <span className="legend-label">Not shown</span>
            <span>Model probabilities. They stay behind the publication boundary above.</span>
          </div>
        </div>
      </figcaption>
    </figure>
  );
}

/**
 * The playground's compact picker shares pitch geometry. Pointer users drop the shot directly;
 * keyboard users set coordinates through the labelled number inputs beside it.
 */
export function ShotPlacementPitch({
  locationX,
  locationY,
  onPlace,
}: {
  locationX: number;
  locationY: number;
  onPlace: (x: number, y: number) => void;
}) {
  function place(event: MouseEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    // viewBox spans x 60..120: only the attacking half is offered, matching where eligible shots live.
    const ratioX = (event.clientX - rect.left) / rect.width;
    const ratioY = (event.clientY - rect.top) / rect.height;
    const x = Math.min(120, Math.max(60, Math.round((60 + ratioX * 60) * 10) / 10));
    const y = Math.min(80, Math.max(0, Math.round(ratioY * 80 * 10) / 10));
    onPlace(x, y);
  }

  return (
    <svg
      viewBox={`60 0 60 80`}
      role="img"
      aria-label={`Shot placement preview at x ${locationX.toFixed(1)}, y ${locationY.toFixed(1)}. Click to move the shot; exact coordinates go in the number inputs.`}
      onClick={place}
      style={{ display: "block", width: "100%", height: "auto", cursor: "crosshair", color: "var(--teal)" }}
    >
      <rect x={60} y={0} width={60} height={80} fill="none" stroke="currentColor" strokeWidth={0.3} opacity={0.45} />
      <rect x={102} y={18} width={18} height={44} fill="none" stroke="currentColor" strokeWidth={0.3} opacity={0.45} />
      <rect x={114} y={30} width={6} height={20} fill="none" stroke="currentColor" strokeWidth={0.3} opacity={0.45} />
      <circle cx={108} cy={40} r={0.35} fill="currentColor" opacity={0.45} />
      <line x1={120} y1={36} x2={120} y2={44} stroke="currentColor" strokeWidth={0.9} />
      {/* guiding lines so pointer placement reads against the box */}
      <line x1={locationX} y1={locationY} x2={120} y2={40} stroke="var(--accent)" strokeWidth={0.3} strokeDasharray="1.2 0.9" opacity={0.8} />
      <circle cx={locationX} cy={locationY} r={1.4} fill="var(--accent)" stroke="var(--background)" strokeWidth={0.3} />
      <text x={62.5} y={77.5} fontSize={3.4} fill="var(--muted)" fontFamily="var(--font-geist-sans), Arial, sans-serif">
        attacking right · click to place
      </text>
    </svg>
  );
}
