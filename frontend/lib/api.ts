/**
 * Types and fetching for the read-only shot endpoint.
 *
 * These mirror the legacy FastAPI recorded-shot response models. This adapter intentionally carries
 * no model probability; model-aware WP3.1 responses live in `model-api.ts` and have their own
 * provenance, validation, and publication-gate contract.
 */

/** Local development default. Deployments must set `NEXT_PUBLIC_API_BASE` and are not given one. */
export const LOCAL_API_BASE = "http://127.0.0.1:8000";

export class ApiBaseNotConfiguredError extends Error {
  constructor() {
    super(
      "NEXT_PUBLIC_API_BASE is not set. A production build has no default API URL: falling back " +
        "to localhost would make a misconfigured deployment look like an unreachable backend.",
    );
    this.name = "ApiBaseNotConfiguredError";
  }
}

/**
 * Resolve the API origin from the environment.
 *
 * Pure and exported so the rule can be tested; `NEXT_PUBLIC_` values are inlined at build time,
 * so the call site below must read `process.env.X` literally rather than through a variable.
 *
 * Two behaviours worth stating:
 *
 *   - A trailing slash is stripped. Paths are concatenated, so `https://api.example.com/` would
 *     otherwise produce `https://api.example.com//baseline`.
 *   - Outside development, an unset value throws instead of defaulting. A deployed frontend
 *     silently pointing at 127.0.0.1 reports "the API could not be reached", which reads as a
 *     backend outage and sends the reader to look at a service that is perfectly healthy.
 */
export function resolveApiBase(
  configured: string | undefined,
  nodeEnv: string | undefined,
): string {
  const trimmed = configured?.trim();
  if (trimmed) {
    return trimmed.replace(/\/+$/, "");
  }
  if (nodeEnv === "production") {
    throw new ApiBaseNotConfiguredError();
  }
  return LOCAL_API_BASE;
}

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

/**
 * Resolved lazily rather than at module load: a throw during module evaluation would break the
 * build itself, which is a worse and more confusing failure than one clear message at request time.
 */
function apiBase(): string {
  return resolveApiBase(process.env.NEXT_PUBLIC_API_BASE, process.env.NODE_ENV);
}

/** The API's own explanation of a failure, when it gave one. Truncated: this reaches the page. */
export async function failureDetail(response: Response): Promise<string | null> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string" && detail.trim()) {
        return detail.trim().slice(0, 300);
      }
    }
  } catch {
    // A non-JSON error body (a proxy's HTML error page, say) carries nothing worth showing.
  }
  return null;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, { cache: "no-store" });
  if (!response.ok) {
    // The status alone sent the reader nowhere: "/baseline responded 503" is true and useless.
    // FastAPI puts the reason in `detail`, so surfacing it turns the page into a first diagnostic.
    const detail = await failureDetail(response);
    throw new Error(
      `${path} responded ${response.status}${detail ? ` — ${detail}` : ""}`,
    );
  }
  return (await response.json()) as T;
}

export function fetchShots(limit = 500, offset = 0): Promise<ShotPage> {
  return getJson<ShotPage>(`/shots?limit=${limit}&offset=${offset}`);
}

/** What a caller got, and what existed to get. Kept together so the two cannot drift apart. */
export interface AllShots {
  shots: Shot[];
  /** The API's unpaged total. If this exceeds `shots.length`, the caller must say so. */
  total: number;
}

/**
 * Page through the bounded endpoint until every shot has been retrieved.
 *
 * The API is deliberately bounded, so "all the shots" means several requests. Fetching one page
 * and describing it as the tournament would be a quiet misstatement - the page claims to show
 * every recorded shot, and with 1,494 in WC 2022 against a 200-row default it would have been
 * showing a third of them.
 *
 * `total` is returned alongside rather than discarded, so the caller can disclose a shortfall if
 * the loop ever stops early. It stops early only at `maxPages`, which exists so a mismatch between
 * client and server cannot turn into an unbounded request loop.
 */
export async function fetchAllShots(
  pageSize = 1000,
  maxPages = 20,
): Promise<AllShots> {
  const first = await fetchShots(pageSize, 0);
  const shots = [...first.shots];

  for (let page = 1; shots.length < first.total && page < maxPages; page += 1) {
    const next = await fetchShots(pageSize, page * pageSize);
    if (next.shots.length === 0) {
      break; // defensive: never loop forever on an endpoint that stops returning rows
    }
    shots.push(...next.shots);
  }

  return { shots, total: first.total };
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
