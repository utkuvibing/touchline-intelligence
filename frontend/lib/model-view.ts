import type { HistoricalShot, ReliabilityRow } from "@/lib/model-api";

export const PITCH_LENGTH = 120;
export const PITCH_WIDTH = 80;

export const MIN_MARKER_RADIUS = 0.45;
export const MAX_MARKER_RADIUS = 2.4;

/**
 * History filter state as flat exact-match values ("" = All).
 *
 * A `type`, not an interface, so it stays structurally assignable to Record<string, string>
 * for the shared presentational FilterBar.
 */
export type HistoricalFilters = {
  match_id: string;
  team: string;
  player: string;
  outcome: string;
  body_part: string;
  technique: string;
  play_pattern: string;
};

export const EMPTY_HISTORICAL_FILTERS: HistoricalFilters = {
  match_id: "",
  team: "",
  player: "",
  outcome: "",
  body_part: "",
  technique: "",
  play_pattern: "",
};

export interface FilterOption {
  value: string;
  label: string;
}

export interface MatchOption extends FilterOption {
  value: string;
}

export function filterHistoricalShots(
  shots: HistoricalShot[],
  filters: HistoricalFilters,
): HistoricalShot[] {
  return shots.filter((shot) => {
    return (
      (!filters.match_id || String(shot.match_id) === filters.match_id) &&
      (!filters.team || shot.team === filters.team) &&
      (!filters.player || shot.player === filters.player) &&
      (!filters.outcome || shot.outcome === filters.outcome) &&
      (!filters.body_part || shot.body_part === filters.body_part) &&
      (!filters.technique || shot.technique === filters.technique) &&
      (!filters.play_pattern || shot.play_pattern === filters.play_pattern)
    );
  });
}

function uniqueSorted(values: string[]): FilterOption[] {
  return [...new Set(values)].sort((left, right) => left.localeCompare(right)).map((value) => ({
    value,
    label: value,
  }));
}

export function filterOptions(shots: HistoricalShot[]) {
  const matches = new Map<number, MatchOption>();
  for (const shot of shots) {
    if (!matches.has(shot.match_id)) {
      const date = shot.match_date ?? "date unavailable";
      matches.set(shot.match_id, {
        value: String(shot.match_id),
        label: `${date} · ${shot.team} v ${shot.opponent}`,
      });
    }
  }

  return {
    matches: [...matches.values()].sort((left, right) => left.label.localeCompare(right.label)),
    teams: uniqueSorted(shots.map((shot) => shot.team)),
    players: uniqueSorted(shots.map((shot) => shot.player)),
    outcomes: uniqueSorted(shots.map((shot) => shot.outcome)),
    bodyParts: uniqueSorted(shots.map((shot) => shot.body_part)),
    techniques: uniqueSorted(shots.map((shot) => shot.technique)),
    playPatterns: uniqueSorted(shots.map((shot) => shot.play_pattern)),
  };
}

/**
 * Convert probability to marker radius while keeping marker area affine in probability.
 *
 * A circle's area is pi*r^2. Substituting this formula makes area equal to
 * pi*(r_min^2 + p*(r_max^2-r_min^2)), so probability is not visually represented by radius.
 */
export function probabilityToRadius(probability: number): number {
  if (!Number.isFinite(probability) || probability < 0 || probability > 1) {
    throw new RangeError("probability must be finite and inside [0, 1]");
  }
  return Math.sqrt(
    MIN_MARKER_RADIUS ** 2 +
      probability * (MAX_MARKER_RADIUS ** 2 - MIN_MARKER_RADIUS ** 2),
  );
}

export function isGoalShot(shot: HistoricalShot): boolean {
  return shot.outcome === "Goal";
}

export function formatProbability(probability: number): string {
  return `${(probability * 100).toFixed(1)}%`;
}

export function formatMetric(value: number): string {
  return value.toFixed(3);
}

export function formatInterval(lower: number, upper: number): string {
  return `${lower.toFixed(3)}–${upper.toFixed(3)}`;
}

export function chartPoint(row: ReliabilityRow, width: number, height: number, padding: number) {
  if (row.mean_prediction === null || row.observed_rate === null) return null;
  const plotWidth = width - padding * 2;
  const plotHeight = height - padding * 2;
  return {
    x: padding + row.mean_prediction * plotWidth,
    y: height - padding - row.observed_rate * plotHeight,
  };
}
