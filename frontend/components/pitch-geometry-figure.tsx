import { PITCH_WIDTH } from "@/lib/model-view";

const GOAL_CENTRE_X = 120;
const GOAL_CENTRE_Y = 40;
const POST_TOP_Y = 36;
const POST_BOTTOM_Y = 44;

/** An illustrative shot location inside the attacking third. */
const SAMPLE_SHOT_X = 94;
const SAMPLE_SHOT_Y = 24;

const distance = Math.hypot(GOAL_CENTRE_X - SAMPLE_SHOT_X, GOAL_CENTRE_Y - SAMPLE_SHOT_Y);

/**
 * Angle subtended by the two posts at the shot, via the same numerically stable
 * cross/dot form the model's feature pipeline uses.
 */
const toTop = { x: GOAL_CENTRE_X - SAMPLE_SHOT_X, y: POST_TOP_Y - SAMPLE_SHOT_Y };
const toBottom = { x: GOAL_CENTRE_X - SAMPLE_SHOT_X, y: POST_BOTTOM_Y - SAMPLE_SHOT_Y };
const cross = toTop.x * toBottom.y - toTop.y * toBottom.x;
const dot = toTop.x * toBottom.x + toTop.y * toBottom.y;
const angleDegrees = (Math.atan2(Math.abs(cross), dot) * 180) / Math.PI;

const LINE = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 0.35,
  opacity: 0.4,
} as const;

/**
 * The two continuous features the released model actually sees, drawn on a StatsBomb 120x80
 * pitch. Illustrative geometry, not a recorded shot row.
 */
export function PitchGeometryFigure() {
  return (
    <figure className="geometry-figure">
      <svg
        viewBox={`0 0 120 ${PITCH_WIDTH}`}
        role="img"
        aria-label={`Pitch diagram of the model's geometry features. An example shot ${distance.toFixed(
          1,
        )} coordinate units from goal sees a ${angleDegrees.toFixed(1)} degree goal angle.`}
      >
        {/* pitch furniture */}
        <rect x={0} y={0} width={120} height={PITCH_WIDTH} {...LINE} />
        <line x1={60} y1={0} x2={60} y2={PITCH_WIDTH} {...LINE} />
        <circle cx={60} cy={40} r={10.5} {...LINE} />
        <rect x={0} y={18} width={18} height={44} {...LINE} />
        <rect x={0 + 102} y={18} width={18} height={44} {...LINE} />
        <rect x={114} y={30} width={6} height={20} {...LINE} />
        <circle cx={108} cy={40} r={0.35} fill="currentColor" opacity={0.4} />
        <line x1={120} y1={36} x2={120} y2={44} stroke="currentColor" strokeWidth={1} />

        {/* visible-angle wedge: shot to post to post */}
        <path
          d={`M ${SAMPLE_SHOT_X} ${SAMPLE_SHOT_Y} L ${GOAL_CENTRE_X} ${POST_TOP_Y} L ${GOAL_CENTRE_X} ${POST_BOTTOM_Y} Z`}
          fill="currentColor"
          opacity={0.16}
          stroke="none"
        />
        <line
          x1={SAMPLE_SHOT_X}
          y1={SAMPLE_SHOT_Y}
          x2={GOAL_CENTRE_X}
          y2={POST_TOP_Y}
          stroke="currentColor"
          strokeWidth={0.25}
          opacity={0.6}
        />
        <line
          x1={SAMPLE_SHOT_X}
          y1={SAMPLE_SHOT_Y}
          x2={GOAL_CENTRE_X}
          y2={POST_BOTTOM_Y}
          stroke="currentColor"
          strokeWidth={0.25}
          opacity={0.6}
        />

        {/* distance line to goal centre */}
        <line
          x1={SAMPLE_SHOT_X}
          y1={SAMPLE_SHOT_Y}
          x2={GOAL_CENTRE_X}
          y2={GOAL_CENTRE_Y}
          stroke="var(--accent)"
          strokeWidth={0.35}
          strokeDasharray="1.2 0.9"
        />

        {/* the shot */}
        <circle
          cx={SAMPLE_SHOT_X}
          cy={SAMPLE_SHOT_Y}
          r={1.2}
          fill="var(--accent)"
          stroke="var(--background)"
          strokeWidth={0.3}
        />

        {/* annotations, sized for a 120-unit-wide viewBox */}
        <text
          x={SAMPLE_SHOT_X - 2.2}
          y={SAMPLE_SHOT_Y - 1.4}
          textAnchor="end"
          className="figure-label"
        >
          shot
        </text>
        <text
          x={(SAMPLE_SHOT_X + GOAL_CENTRE_X) / 2 + 1.5}
          y={(SAMPLE_SHOT_Y + GOAL_CENTRE_Y) / 2 + 3.4}
          textAnchor="middle"
          className="figure-value"
        >
          {distance.toFixed(1)} units
        </text>
        <text x={SAMPLE_SHOT_X - 2.2} y={SAMPLE_SHOT_Y + 8.5} textAnchor="end" className="figure-value">
          {angleDegrees.toFixed(1)}°
        </text>
        <text x={60} y={77.5} textAnchor="middle" className="figure-label">
          StatsBomb 120 × 80
        </text>
      </svg>
      <figcaption className="geometry-caption">
        <span className="figure-tag">What the model sees</span>
        Two continuous features come from the shot location: distance to goal and the angle of goal
        visible to the shooter. Everything else is recorded shot context. No tracking data, and no
        provider xG at any point.
      </figcaption>
    </figure>
  );
}
