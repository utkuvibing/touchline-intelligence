import { resolveApiBase } from "@/lib/api";

export const HISTORICAL_PAGE_SIZE = 1000;

export const PROVENANCE_FIELDS = [
  "model_version",
  "release_id",
  "serving_manifest_sha256",
  "release_manifest_sha256",
  "release_manifest_file_sha256",
  "artifact_sha256",
  "calibration_decision_sha256",
] as const;

export type ProvenanceField = (typeof PROVENANCE_FIELDS)[number];

export type ProvenanceIdentity = Record<ProvenanceField, string>;

export interface ModelMetadata extends ProvenanceIdentity {
  release_status: "m2_qualified";
  qualification_serving_status: "not_served";
  runtime_status: "ready";
  candidate: string;
  estimator: string;
  calibration: string;
  adopted_variant: "calibrated";
  output: string;
  scopes: {
    development: {
      competitions: string[];
      shots: number;
      matches: number;
      role: "model_development";
    };
    calibration: {
      competition: "FIFA World Cup 2022";
      shots: number;
      matches: number;
      role: "platt_calibration_and_adoption";
    };
    tournament_holdout: {
      competition: "UEFA Euro 2024";
      shots: number;
      matches: number;
      role: "one_time_final_evaluation";
    };
  };
  input_contract: {
    coordinates: {
      system: "StatsBomb";
      location_x: { minimum: number; maximum: number };
      location_y: { minimum: number; maximum: number };
    };
    categorical_policy: "exact_frozen_vocabulary_with_unseen_as_reference";
    fields: Record<
      "body_part" | "technique" | "play_pattern",
      {
        reference: string;
        retained: string[];
        rare_members: string[];
      }
    >;
  };
}

export interface ReliabilityRow {
  bin: number;
  lower: number;
  upper: number;
  count: number;
  positive_count: number;
  mean_prediction: number | null;
  observed_rate: number | null;
}

export interface CalibrationReliabilityRow extends Omit<ReliabilityRow, "mean_prediction"> {
  raw_mean_prediction: number | null;
  calibrated_mean_prediction: number | null;
}

export interface ModelMetrics extends ProvenanceIdentity {
  evidence_source: {
    holdout_metrics_sha256: string;
    evidence_status: "qualified_m2_evidence";
    recomputed_at_request_time: false;
  };
  calibration_adoption: {
    split: "FIFA World Cup 2022";
    role: "calibration";
    shots: number;
    matches: number;
    adopted_variant: "calibrated";
    supported_raw_anchor_bins: number;
    raw: {
      log_loss: number;
      brier: number;
      max_supported_calibration_deviation: number;
    };
    calibrated: {
      log_loss: number;
      brier: number;
      max_supported_calibration_deviation: number;
    };
    raw_anchor_reliability: CalibrationReliabilityRow[];
  };
  tournament_holdout: {
    split: "UEFA Euro 2024";
    role: "one_time_tournament_holdout";
    shots: number;
    matches: number;
    goals: number;
    observed_prevalence: number;
    adopted_variant: "calibrated";
    proper_scoring: {
      log_loss: number;
      brier: number;
    };
    discrimination: {
      roc_auc: number;
      pr_auc: number;
    };
    uncertainty: {
      method: "match_clustered_paired_bootstrap";
      confidence_level: number;
      repetitions: number;
      seed: number;
      log_loss: { lower: number; upper: number };
      brier: { lower: number; upper: number };
    };
    reliability: ReliabilityRow[];
    raw_comparator: {
      proper_scoring: {
        log_loss: number;
        brier: number;
      };
      discrimination: {
        roc_auc: number;
        pr_auc: number;
      };
      calibrated_minus_raw: {
        log_loss: number;
        brier: number;
        log_loss_interval: { lower: number; upper: number };
        brier_interval: { lower: number; upper: number };
      };
    };
  };
}

export interface HistoricalShot {
  shot_id: string;
  match_id: number;
  match_date: string | null;
  competition_stage: string | null;
  team: string;
  opponent: string;
  player: string;
  period: number;
  minute: number | null;
  second: number | null;
  location_x: number;
  location_y: number;
  outcome: string;
  shot_type: string;
  body_part: string;
  technique: string;
  play_pattern: string;
  calibrated_probability: number;
}

export interface HistoricalShotsPage extends ProvenanceIdentity {
  cohort: "FIFA World Cup 2022 eligible non-penalty shots";
  split_role: "calibration_data_historical_predictions";
  historical_prediction_caveat: string;
  shots: HistoricalShot[];
  total: number;
  limit: number;
  offset: number;
}

export interface HistoricalShotCollection extends HistoricalShotsPage {
  page_count: number;
}

export interface ModelApiErrorInfo {
  code: string;
  message: string;
  status: number | null;
}

export class ModelApiError extends Error {
  readonly code: string;
  readonly status: number | null;

  constructor({ code, message, status }: ModelApiErrorInfo) {
    super(message);
    this.name = "ModelApiError";
    this.code = code;
    this.status = status;
  }

  toInfo(): ModelApiErrorInfo {
    return { code: this.code, message: this.message, status: this.status };
  }
}

export class ModelContractError extends Error {
  readonly code = "contract_error";

  constructor(message: string) {
    super(message);
    this.name = "ModelContractError";
  }

  toInfo(): ModelApiErrorInfo {
    return { code: this.code, message: this.message, status: null };
  }
}

export class ProvenanceMismatchError extends Error {
  readonly code = "provenance_mismatch";

  constructor(readonly field: ProvenanceField) {
    super(`model provenance differs at ${field}`);
    this.name = "ProvenanceMismatchError";
  }

  toInfo(): ModelApiErrorInfo {
    return { code: this.code, message: this.message, status: null };
  }
}

interface JsonObject {
  [key: string]: unknown;
}

function object(value: unknown, context: string): JsonObject {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new ModelContractError(`${context} must be an object`);
  }
  return value as JsonObject;
}

function array(value: unknown, context: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new ModelContractError(`${context} must be an array`);
  }
  return value;
}

function string(value: unknown, context: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new ModelContractError(`${context} must be a non-empty string`);
  }
  return value;
}

function nullableString(value: unknown, context: string): string | null {
  if (value === null) return null;
  return string(value, context);
}

function number(value: unknown, context: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new ModelContractError(`${context} must be a finite number`);
  }
  return value;
}

function boundedNumber(value: unknown, context: string, minimum: number, maximum: number): number {
  const parsed = number(value, context);
  if (parsed < minimum || parsed > maximum) {
    throw new ModelContractError(`${context} must be inside [${minimum}, ${maximum}]`);
  }
  return parsed;
}

function integer(value: unknown, context: string, minimum = 0): number {
  const parsed = number(value, context);
  if (!Number.isInteger(parsed) || parsed < minimum) {
    throw new ModelContractError(`${context} must be an integer >= ${minimum}`);
  }
  return parsed;
}

function nullableBoundedNumber(
  value: unknown,
  context: string,
  minimum: number,
  maximum: number,
): number | null {
  if (value === null) return null;
  return boundedNumber(value, context, minimum, maximum);
}

function nullableInteger(value: unknown, context: string, minimum = 0): number | null {
  if (value === null) return null;
  return integer(value, context, minimum);
}

function literal<T extends string>(value: unknown, expected: T, context: string): T {
  if (value !== expected) {
    throw new ModelContractError(`${context} must be ${expected}`);
  }
  return expected;
}

function falseBoolean(value: unknown, context: string): false {
  if (value !== false) {
    throw new ModelContractError(`${context} must be false`);
  }
  return false;
}

function stringList(value: unknown, context: string): string[] {
  return array(value, context).map((entry, index) => string(entry, `${context}[${index}]`));
}

function parseProvenance(value: unknown, context: string): ProvenanceIdentity {
  const source = object(value, context);
  return Object.fromEntries(
    PROVENANCE_FIELDS.map((field) => [field, string(source[field], `${context}.${field}`)]),
  ) as ProvenanceIdentity;
}

function parseScope(value: unknown, context: string) {
  const source = object(value, context);
  return {
    competitions: stringList(source.competitions, `${context}.competitions`),
    shots: integer(source.shots, `${context}.shots`),
    matches: integer(source.matches, `${context}.matches`),
    role: literal(source.role, "model_development", `${context}.role`),
  };
}

function parseCalibrationScope(value: unknown, context: string) {
  const source = object(value, context);
  return {
    competition: literal(source.competition, "FIFA World Cup 2022", `${context}.competition`),
    shots: integer(source.shots, `${context}.shots`),
    matches: integer(source.matches, `${context}.matches`),
    role: literal(source.role, "platt_calibration_and_adoption", `${context}.role`),
  };
}

function parseHoldoutScope(value: unknown, context: string) {
  const source = object(value, context);
  return {
    competition: literal(source.competition, "UEFA Euro 2024", `${context}.competition`),
    shots: integer(source.shots, `${context}.shots`),
    matches: integer(source.matches, `${context}.matches`),
    role: literal(source.role, "one_time_final_evaluation", `${context}.role`),
  };
}

function parseCategoryContract(value: unknown, context: string) {
  const source = object(value, context);
  return {
    reference: string(source.reference, `${context}.reference`),
    retained: stringList(source.retained, `${context}.retained`),
    rare_members: stringList(source.rare_members, `${context}.rare_members`),
  };
}

export function parseModelMetadata(value: unknown): ModelMetadata {
  const source = object(value, "model metadata");
  const input = object(source.input_contract, "model metadata.input_contract");
  const coordinates = object(input.coordinates, "model metadata.input_contract.coordinates");
  const fields = object(input.fields, "model metadata.input_contract.fields");

  return {
    ...parseProvenance(source, "model metadata"),
    release_status: literal(source.release_status, "m2_qualified", "release_status"),
    qualification_serving_status: literal(
      source.qualification_serving_status,
      "not_served",
      "qualification_serving_status",
    ),
    runtime_status: literal(source.runtime_status, "ready", "runtime_status"),
    candidate: string(source.candidate, "candidate"),
    estimator: string(source.estimator, "estimator"),
    calibration: string(source.calibration, "calibration"),
    adopted_variant: literal(source.adopted_variant, "calibrated", "adopted_variant"),
    output: string(source.output, "output"),
    scopes: {
      development: parseScope(object(source.scopes, "scopes").development, "scopes.development"),
      calibration: parseCalibrationScope(
        object(source.scopes, "scopes").calibration,
        "scopes.calibration",
      ),
      tournament_holdout: parseHoldoutScope(
        object(source.scopes, "scopes").tournament_holdout,
        "scopes.tournament_holdout",
      ),
    },
    input_contract: {
      coordinates: {
        system: literal(coordinates.system, "StatsBomb", "coordinates.system"),
        location_x: {
          minimum: number(coordinates.location_x && object(coordinates.location_x, "location_x").minimum, "location_x.minimum"),
          maximum: number(coordinates.location_x && object(coordinates.location_x, "location_x").maximum, "location_x.maximum"),
        },
        location_y: {
          minimum: number(coordinates.location_y && object(coordinates.location_y, "location_y").minimum, "location_y.minimum"),
          maximum: number(coordinates.location_y && object(coordinates.location_y, "location_y").maximum, "location_y.maximum"),
        },
      },
      categorical_policy: literal(
        input.categorical_policy,
        "exact_frozen_vocabulary_with_unseen_as_reference",
        "categorical_policy",
      ),
      fields: {
        body_part: parseCategoryContract(fields.body_part, "fields.body_part"),
        technique: parseCategoryContract(fields.technique, "fields.technique"),
        play_pattern: parseCategoryContract(fields.play_pattern, "fields.play_pattern"),
      },
    },
  };
}

function parseInterval(value: unknown, context: string) {
  const source = object(value, context);
  return {
    lower: number(source.lower, `${context}.lower`),
    upper: number(source.upper, `${context}.upper`),
  };
}

function parseReliability(value: unknown, context: string): ReliabilityRow {
  const source = object(value, context);
  return {
    bin: integer(source.bin, `${context}.bin`),
    lower: boundedNumber(source.lower, `${context}.lower`, 0, 1),
    upper: boundedNumber(source.upper, `${context}.upper`, 0, 1),
    count: integer(source.count, `${context}.count`),
    positive_count: integer(source.positive_count, `${context}.positive_count`),
    mean_prediction: nullableBoundedNumber(
      source.mean_prediction,
      `${context}.mean_prediction`,
      0,
      1,
    ),
    observed_rate: nullableBoundedNumber(source.observed_rate, `${context}.observed_rate`, 0, 1),
  };
}

function parseCalibrationReliability(value: unknown, context: string): CalibrationReliabilityRow {
  const source = object(value, context);
  return {
    bin: integer(source.bin, `${context}.bin`),
    lower: boundedNumber(source.lower, `${context}.lower`, 0, 1),
    upper: boundedNumber(source.upper, `${context}.upper`, 0, 1),
    count: integer(source.count, `${context}.count`),
    positive_count: integer(source.positive_count, `${context}.positive_count`),
    raw_mean_prediction: nullableBoundedNumber(
      source.raw_mean_prediction,
      `${context}.raw_mean_prediction`,
      0,
      1,
    ),
    calibrated_mean_prediction: nullableBoundedNumber(
      source.calibrated_mean_prediction,
      `${context}.calibrated_mean_prediction`,
      0,
      1,
    ),
    observed_rate: nullableBoundedNumber(source.observed_rate, `${context}.observed_rate`, 0, 1),
  };
}

function parseScores(value: unknown, context: string) {
  const source = object(value, context);
  return {
    log_loss: number(source.log_loss, `${context}.log_loss`),
    brier: number(source.brier, `${context}.brier`),
    max_supported_calibration_deviation: number(
      source.max_supported_calibration_deviation,
      `${context}.max_supported_calibration_deviation`,
    ),
  };
}

function parseProperScoring(value: unknown, context: string) {
  const source = object(value, context);
  return {
    log_loss: number(source.log_loss, `${context}.log_loss`),
    brier: number(source.brier, `${context}.brier`),
  };
}

function parseDiscrimination(value: unknown, context: string) {
  const source = object(value, context);
  return {
    roc_auc: number(source.roc_auc, `${context}.roc_auc`),
    pr_auc: number(source.pr_auc, `${context}.pr_auc`),
  };
}

export function parseModelMetrics(value: unknown): ModelMetrics {
  const source = object(value, "model metrics");
  const evidence = object(source.evidence_source, "evidence_source");
  const adoption = object(source.calibration_adoption, "calibration_adoption");
  const holdout = object(source.tournament_holdout, "tournament_holdout");
  const uncertainty = object(holdout.uncertainty, "tournament_holdout.uncertainty");
  const rawComparator = object(holdout.raw_comparator, "tournament_holdout.raw_comparator");
  const effect = object(rawComparator.calibrated_minus_raw, "calibrated_minus_raw");

  return {
    ...parseProvenance(source, "model metrics"),
    evidence_source: {
      holdout_metrics_sha256: string(
        evidence.holdout_metrics_sha256,
        "evidence_source.holdout_metrics_sha256",
      ),
      evidence_status: literal(
        evidence.evidence_status,
        "qualified_m2_evidence",
        "evidence_source.evidence_status",
      ),
      recomputed_at_request_time: falseBoolean(
        evidence.recomputed_at_request_time,
        "evidence_source.recomputed_at_request_time",
      ),
    },
    calibration_adoption: {
      split: literal(adoption.split, "FIFA World Cup 2022", "calibration_adoption.split"),
      role: literal(adoption.role, "calibration", "calibration_adoption.role"),
      shots: integer(adoption.shots, "calibration_adoption.shots"),
      matches: integer(adoption.matches, "calibration_adoption.matches"),
      adopted_variant: literal(
        adoption.adopted_variant,
        "calibrated",
        "calibration_adoption.adopted_variant",
      ),
      supported_raw_anchor_bins: integer(
        adoption.supported_raw_anchor_bins,
        "calibration_adoption.supported_raw_anchor_bins",
      ),
      raw: parseScores(adoption.raw, "calibration_adoption.raw"),
      calibrated: parseScores(adoption.calibrated, "calibration_adoption.calibrated"),
      raw_anchor_reliability: array(
        adoption.raw_anchor_reliability,
        "calibration_adoption.raw_anchor_reliability",
      ).map((row, index) =>
        parseCalibrationReliability(row, `calibration_adoption.raw_anchor_reliability[${index}]`),
      ),
    },
    tournament_holdout: {
      split: literal(holdout.split, "UEFA Euro 2024", "tournament_holdout.split"),
      role: literal(
        holdout.role,
        "one_time_tournament_holdout",
        "tournament_holdout.role",
      ),
      shots: integer(holdout.shots, "tournament_holdout.shots"),
      matches: integer(holdout.matches, "tournament_holdout.matches"),
      goals: integer(holdout.goals, "tournament_holdout.goals"),
      observed_prevalence: boundedNumber(
        holdout.observed_prevalence,
        "tournament_holdout.observed_prevalence",
        0,
        1,
      ),
      adopted_variant: literal(
        holdout.adopted_variant,
        "calibrated",
        "tournament_holdout.adopted_variant",
      ),
      proper_scoring: parseProperScoring(
        holdout.proper_scoring,
        "tournament_holdout.proper_scoring",
      ),
      discrimination: parseDiscrimination(
        holdout.discrimination,
        "tournament_holdout.discrimination",
      ),
      uncertainty: {
        method: literal(
          uncertainty.method,
          "match_clustered_paired_bootstrap",
          "tournament_holdout.uncertainty.method",
        ),
        confidence_level: boundedNumber(
          uncertainty.confidence_level,
          "tournament_holdout.uncertainty.confidence_level",
          0,
          1,
        ),
        repetitions: integer(
          uncertainty.repetitions,
          "tournament_holdout.uncertainty.repetitions",
        ),
        seed: integer(uncertainty.seed, "tournament_holdout.uncertainty.seed"),
        log_loss: parseInterval(
          uncertainty.log_loss,
          "tournament_holdout.uncertainty.log_loss",
        ),
        brier: parseInterval(uncertainty.brier, "tournament_holdout.uncertainty.brier"),
      },
      reliability: array(holdout.reliability, "tournament_holdout.reliability").map(
        (row, index) => parseReliability(row, `tournament_holdout.reliability[${index}]`),
      ),
      raw_comparator: {
        proper_scoring: parseProperScoring(
          object(rawComparator.proper_scoring, "raw_comparator.proper_scoring"),
          "raw_comparator.proper_scoring",
        ),
        discrimination: parseDiscrimination(
          object(rawComparator.discrimination, "raw_comparator.discrimination"),
          "raw_comparator.discrimination",
        ),
        calibrated_minus_raw: {
          log_loss: number(effect.log_loss, "calibrated_minus_raw.log_loss"),
          brier: number(effect.brier, "calibrated_minus_raw.brier"),
          log_loss_interval: parseInterval(
            effect.log_loss_interval,
            "calibrated_minus_raw.log_loss_interval",
          ),
          brier_interval: parseInterval(
            effect.brier_interval,
            "calibrated_minus_raw.brier_interval",
          ),
        },
      },
    },
  };
}

function parseHistoricalShot(value: unknown, context: string): HistoricalShot {
  const source = object(value, context);
  return {
    shot_id: string(source.shot_id, `${context}.shot_id`),
    match_id: integer(source.match_id, `${context}.match_id`, 1),
    match_date: nullableString(source.match_date, `${context}.match_date`),
    competition_stage: nullableString(source.competition_stage, `${context}.competition_stage`),
    team: string(source.team, `${context}.team`),
    opponent: string(source.opponent, `${context}.opponent`),
    player: string(source.player, `${context}.player`),
    period: integer(source.period, `${context}.period`, 1),
    minute: nullableInteger(source.minute, `${context}.minute`),
    second: nullableInteger(source.second, `${context}.second`),
    location_x: number(source.location_x, `${context}.location_x`),
    location_y: number(source.location_y, `${context}.location_y`),
    outcome: string(source.outcome, `${context}.outcome`),
    shot_type: string(source.shot_type, `${context}.shot_type`),
    body_part: string(source.body_part, `${context}.body_part`),
    technique: string(source.technique, `${context}.technique`),
    play_pattern: string(source.play_pattern, `${context}.play_pattern`),
    calibrated_probability: boundedNumber(
      source.calibrated_probability,
      `${context}.calibrated_probability`,
      0,
      1,
    ),
  };
}

export function parseHistoricalShotsPage(value: unknown): HistoricalShotsPage {
  const source = object(value, "historical shots page");
  return {
    ...parseProvenance(source, "historical shots page"),
    cohort: literal(
      source.cohort,
      "FIFA World Cup 2022 eligible non-penalty shots",
      "cohort",
    ),
    split_role: literal(
      source.split_role,
      "calibration_data_historical_predictions",
      "split_role",
    ),
    historical_prediction_caveat: string(
      source.historical_prediction_caveat,
      "historical_prediction_caveat",
    ),
    shots: array(source.shots, "shots").map((shot, index) =>
      parseHistoricalShot(shot, `shots[${index}]`),
    ),
    total: integer(source.total, "total"),
    limit: integer(source.limit, "limit", 1),
    offset: integer(source.offset, "offset"),
  };
}

function apiBase(): string {
  return resolveApiBase(process.env.NEXT_PUBLIC_API_BASE, process.env.NODE_ENV);
}

function truncate(value: string): string {
  return value.trim().slice(0, 300);
}

function isStructuredErrorDetail(value: unknown): value is JsonObject {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const detail = value as JsonObject;
  return (
    (detail.field === null || typeof detail.field === "string") &&
    typeof detail.code === "string" &&
    typeof detail.message === "string"
  );
}

function hasStructuredErrorDetails(value: unknown): value is JsonObject[] {
  if (!Array.isArray(value)) return false;
  return value.every(isStructuredErrorDetail);
}

function parseErrorBody(value: unknown): { code: string; message: string } | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  const source = value as JsonObject;
  const error = source.error;
  if (error !== null && typeof error === "object" && !Array.isArray(error)) {
    const detail = error as JsonObject;
    if (
      typeof detail.code === "string" &&
      typeof detail.message === "string" &&
      hasStructuredErrorDetails(detail.details) &&
      (detail.code !== "publication_gate_closed" || detail.details.length === 0)
    ) {
      return { code: detail.code, message: detail.message };
    }
  }
  if (typeof source.detail === "string") {
    return { code: "http_error", message: source.detail };
  }
  return null;
}

async function requestJson(path: string): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(`${apiBase()}${path}`, { cache: "no-store" });
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : "network request failed";
    throw new ModelApiError({ code: "network_error", message: truncate(message), status: null });
  }

  const bodyText = await response.text();
  let body: unknown = null;
  if (bodyText.trim()) {
    try {
      body = JSON.parse(bodyText) as unknown;
    } catch {
      body = null;
    }
  }

  if (!response.ok) {
    const parsed = parseErrorBody(body);
    throw new ModelApiError({
      code: parsed?.code ?? `http_${response.status}`,
      message: truncate(parsed?.message ?? `${path} responded ${response.status}`),
      status: response.status,
    });
  }

  return body;
}

export async function fetchModelMetadata(): Promise<ModelMetadata> {
  return parseModelMetadata(await requestJson("/model"));
}

export async function fetchModelMetrics(): Promise<ModelMetrics> {
  return parseModelMetrics(await requestJson("/model/metrics"));
}

export async function fetchHistoricalShotsPage(
  limit = HISTORICAL_PAGE_SIZE,
  offset = 0,
): Promise<HistoricalShotsPage> {
  if (!Number.isInteger(limit) || limit < 1 || limit > HISTORICAL_PAGE_SIZE) {
    throw new RangeError(`historical page limit must be inside [1, ${HISTORICAL_PAGE_SIZE}]`);
  }
  if (!Number.isInteger(offset) || offset < 0) {
    throw new RangeError("historical page offset must be a non-negative integer");
  }
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return parseHistoricalShotsPage(await requestJson(`/model/shots?${params.toString()}`));
}

function addUniqueShots(
  target: HistoricalShot[],
  seen: Set<string>,
  source: HistoricalShot[],
): void {
  for (const shot of source) {
    if (seen.has(shot.shot_id)) {
      throw new ModelContractError(`historical pagination repeated shot ${shot.shot_id}`);
    }
    seen.add(shot.shot_id);
    target.push(shot);
  }
}

export async function fetchAllHistoricalShots(
  pageSize = HISTORICAL_PAGE_SIZE,
): Promise<HistoricalShotCollection> {
  const first = await fetchHistoricalShotsPage(pageSize, 0);
  if (first.offset !== 0 || first.limit !== pageSize) {
    throw new ModelContractError("historical first page does not echo the requested pagination");
  }

  const historicalPredictionCaveat = first.historical_prediction_caveat;
  const shots: HistoricalShot[] = [];
  const seen = new Set<string>();
  if (first.shots.length > first.limit) {
    throw new ModelContractError("historical first page exceeds its returned limit");
  }
  addUniqueShots(shots, seen, first.shots);
  if (shots.length > first.total) {
    throw new ModelContractError("historical page contains more shots than its returned total");
  }
  if (first.total > 0 && first.shots.length === 0) {
    throw new ModelContractError("historical pagination started with an empty page");
  }
  if (shots.length < first.total && first.shots.length < pageSize) {
    throw new ModelContractError("historical pagination returned a short first page before its total");
  }

  let offset = pageSize;
  let pageCount = 1;
  while (shots.length < first.total) {
    const page = await fetchHistoricalShotsPage(pageSize, offset);
    pageCount += 1;
    if (page.offset !== offset || page.limit !== pageSize || page.total !== first.total) {
      throw new ModelContractError("historical pagination changed its total or offset contract");
    }
    if (page.shots.length > page.limit) {
      throw new ModelContractError("historical page exceeds its returned limit");
    }
    if (page.historical_prediction_caveat !== historicalPredictionCaveat) {
      throw new ModelContractError("historical pagination changed its prediction caveat");
    }
    assertProvenanceEqual(first, page);
    if (page.shots.length === 0) {
      throw new ModelContractError("historical pagination stopped before its returned total");
    }
    addUniqueShots(shots, seen, page.shots);
    if (shots.length > first.total) {
      throw new ModelContractError("historical pagination exceeded its returned total");
    }
    if (shots.length < first.total && page.shots.length < pageSize) {
      throw new ModelContractError("historical pagination returned a short page before its total");
    }
    offset += pageSize;
    if (pageCount > Math.ceil(first.total / pageSize) + 1) {
      throw new ModelContractError("historical pagination exceeded its bounded page count");
    }
  }

  if (shots.length !== first.total) {
    throw new ModelContractError("historical pagination did not satisfy its returned total");
  }

  return { ...first, shots, page_count: pageCount };
}

export function assertProvenanceEqual(
  expected: ProvenanceIdentity,
  actual: ProvenanceIdentity,
): void {
  for (const field of PROVENANCE_FIELDS) {
    if (expected[field] !== actual[field]) {
      throw new ProvenanceMismatchError(field);
    }
  }
}

export function asModelApiErrorInfo(cause: unknown): ModelApiErrorInfo {
  if (cause instanceof ModelApiError || cause instanceof ModelContractError) {
    return cause.toInfo();
  }
  if (cause instanceof ProvenanceMismatchError) {
    return cause.toInfo();
  }
  if (cause instanceof Error) {
    return { code: "frontend_error", message: truncate(cause.message), status: null };
  }
  return { code: "frontend_error", message: "unexpected frontend error", status: null };
}

export function isPublicationGateClosed(error: ModelApiErrorInfo): boolean {
  return error.code === "publication_gate_closed" && error.status === 403;
}
