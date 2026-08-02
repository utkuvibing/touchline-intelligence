/**
 * Raw shot map: every recorded shot at its recorded location.
 *
 * Encoding rules, deliberately restrictive while M0 has no evaluated model:
 *
 *   - Every marker is the SAME SIZE. Size-by-value is how xG maps are drawn, and using it here
 *     would imply a quality estimate that does not exist.
 *   - There is no colour ramp and no heat map. A continuous gradient reads as a probability
 *     surface; this is a scatter of things that happened.
 *   - The only visual distinction is goal versus non-goal, which is the recorded outcome — a
 *     fact from the source, not an inference.
 *
 * Coordinates are StatsBomb's: 120 long by 80 wide, attacking left-to-right. Only the attacking
 * half is drawn, because that is where shots are.
 */

import { PITCH_WIDTH, isGoal, type PlottableShot } from "@/lib/api";

/** Left edge of the drawn area. Shots behind the halfway line are rare but are still clipped in. */
const VIEW_MIN_X = 60;
const VIEW_LENGTH = 120 - VIEW_MIN_X;

const MARKER_RADIUS = 0.7;

/**
 * Sizing, and why each part of it matters.
 *
 * `width: 100%` with `height: auto` and no explicit height leaves the proportions entirely to the
 * viewBox, so the drawn half stays exactly 60 long by 80 wide — a 0.75 ratio — at every rendered
 * size, and the map still shrinks to fit a narrow screen rather than overflowing it.
 *
 * `maxWidth` therefore only caps how large the map may grow. At 56rem it rendered around 1,200px
 * tall on a desktop and pushed the conversion rate and its caveat below the fold; the map is one
 * part of the page, not the page.
 */
const MAP_STYLE = { width: "100%", height: "auto", maxWidth: "44rem" } as const;

interface ShotMapProps {
  shots: PlottableShot[];
}

function PitchMarkings() {
  const line = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 0.3,
    opacity: 0.45,
  };

  return (
    <g aria-hidden="true">
      <rect x={VIEW_MIN_X} y={0} width={VIEW_LENGTH} height={PITCH_WIDTH} {...line} />
      {/* Penalty area: 18 yards from the goal line, 44 wide. */}
      <rect x={102} y={18} width={18} height={44} {...line} />
      {/* Six-yard box. */}
      <rect x={114} y={30} width={6} height={20} {...line} />
      {/* Penalty spot. */}
      <circle cx={108} cy={40} r={0.35} fill="currentColor" opacity={0.45} />
      {/* Goal. */}
      <line x1={120} y1={36} x2={120} y2={44} stroke="currentColor" strokeWidth={0.9} />
      {/* Halfway line, at the left edge of the drawn area. */}
      <line
        x1={VIEW_MIN_X}
        y1={0}
        x2={VIEW_MIN_X}
        y2={PITCH_WIDTH}
        stroke="currentColor"
        strokeWidth={0.3}
        opacity={0.45}
      />
    </g>
  );
}

export function ShotMap({ shots }: ShotMapProps) {
  const goals = shots.filter(isGoal);
  const others = shots.filter((shot) => !isGoal(shot));

  return (
    <figure>
      <svg
        viewBox={`${VIEW_MIN_X} 0 ${VIEW_LENGTH} ${PITCH_WIDTH}`}
        role="img"
        aria-label={`Shot map: ${shots.length} recorded shots, of which ${goals.length} were goals. Attacking towards the right.`}
        style={MAP_STYLE}
      >
        <PitchMarkings />

        {/* Non-goals first so the goals are not hidden underneath them. */}
        {others.map((shot) => (
          <circle
            key={shot.shot_id}
            cx={shot.location_x}
            cy={shot.location_y}
            r={MARKER_RADIUS}
            fill="none"
            stroke="currentColor"
            strokeWidth={0.25}
            opacity={0.55}
          >
            <title>{describe(shot)}</title>
          </circle>
        ))}

        {goals.map((shot) => (
          <circle
            key={shot.shot_id}
            cx={shot.location_x}
            cy={shot.location_y}
            r={MARKER_RADIUS}
            fill="currentColor"
          >
            <title>{describe(shot)}</title>
          </circle>
        ))}
      </svg>

      <figcaption>
        <p>
          Each marker is one recorded shot at its recorded location, attacking towards the right.
          Filled markers are goals; outlined markers are every other outcome.
        </p>
        <p>
          <strong>
            All markers are the same size and there is no colour scale. Nothing here is an estimate
            of chance quality.
          </strong>{" "}
          Marker size and colour gradients are how expected-goals maps encode a model output, and
          this project has no evaluated model yet.
        </p>
      </figcaption>
    </figure>
  );
}

function describe(shot: PlottableShot): string {
  const when = shot.minute === null ? "" : `${shot.minute}' `;
  const who = shot.player ?? "unattributed";
  return `${when}${who} (${shot.team} vs ${shot.opponent}) — ${shot.outcome ?? "unknown outcome"}`;
}
