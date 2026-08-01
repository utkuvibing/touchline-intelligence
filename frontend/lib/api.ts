/**
 * Types and fetching for the read-only shot endpoint.
 *
 * These mirror the FastAPI response models. There is deliberately no probability, rating or
 * estimate anywhere in this file — the API does not serve one, and adding a placeholder here
 * would be the first step towards rendering a number nothing has evaluated.
 */

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

/** StatsBomb pitch dimensions, in the units the coordinates are recorded in. */
export const PITCH_LENGTH = 120;
export const PITCH_WIDTH = 80;

export interface Shot {
  shot_id: string;
  match_id: number;
  match_date: string | null;
  competition_stage: string | null;
  team: string;
  opponent: string;
  player: string | null;
  period: number | null;
  minute: number | null;
  second: number | null;
  /** Null where the source recorded no location. Such shots cannot be plotted, and are counted instead. */
  location_x: number | null;
  location_y: number | null;
  outcome: string | null;
  shot_type: string | null;
  body_part: string | null;
  technique: string | null;
}

export interface ShotPage {
  shots: Shot[];
  total: number;
  limit: number;
  offset: number;
}

export interface ConversionRate {
  method: "descriptive-prevalence";
  conversion_rate: number;
  shots: number;
  goals: number;
  cohort: string;
  caveat: string;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`${path} responded ${response.status}`);
  }
  return (await response.json()) as T;
}

export function fetchShots(limit = 500): Promise<ShotPage> {
  return getJson<ShotPage>(`/shots?limit=${limit}`);
}

export function fetchConversionRate(): Promise<ConversionRate> {
  return getJson<ConversionRate>("/baseline");
}

/** A shot that has coordinates, so it can actually be drawn. */
export type PlottableShot = Shot & { location_x: number; location_y: number };

export function isPlottable(shot: Shot): shot is PlottableShot {
  return shot.location_x !== null && shot.location_y !== null;
}

/**
 * Goal or not.
 *
 * This is the *recorded outcome*, not an estimate. It is the only distinction the map encodes,
 * precisely because it is the only one the data states as fact.
 */
export function isGoal(shot: Shot): boolean {
  return shot.outcome === "Goal";
}
