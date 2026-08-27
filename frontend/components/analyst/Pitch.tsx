import { PITCH_LENGTH, PITCH_WIDTH } from "@/lib/model-view";

/** Full-pitch viewBox in StatsBomb coordinates, attacking right. */
export const PITCH_VIEWBOX = `0 0 ${PITCH_LENGTH} ${PITCH_WIDTH}`;

const LINE = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 0.3,
  opacity: 0.45,
} as const;

/**
 * The pitch furniture every shot map shares: boundary, halfway line and circle, both penalty
 * areas with their six-yard boxes, spots and goals. One drawing keeps the two maps from
 * drifting apart visually.
 */
export function PitchMarkings() {
  return (
    <g aria-hidden="true">
      <rect x={0} y={0} width={PITCH_LENGTH} height={PITCH_WIDTH} {...LINE} />
      <line x1={60} y1={0} x2={60} y2={PITCH_WIDTH} {...LINE} />
      <circle cx={60} cy={40} r={10.5} {...LINE} />
      <circle cx={60} cy={40} r={0.35} fill="currentColor" opacity={0.45} />
      <rect x={0} y={18} width={18} height={44} {...LINE} />
      <rect x={0} y={30} width={6} height={20} {...LINE} />
      <circle cx={13} cy={40} r={0.35} fill="currentColor" opacity={0.45} />
      <rect x={102} y={18} width={18} height={44} {...LINE} />
      <rect x={114} y={30} width={6} height={20} {...LINE} />
      <circle cx={108} cy={40} r={0.35} fill="currentColor" opacity={0.45} />
      <line x1={0} y1={36} x2={0} y2={44} stroke="currentColor" strokeWidth={0.9} />
      <line x1={120} y1={36} x2={120} y2={44} stroke="currentColor" strokeWidth={0.9} />
    </g>
  );
}
