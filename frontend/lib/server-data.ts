import { asModelApiErrorInfo, type ModelApiErrorInfo } from "@/lib/model-api";

/**
 * How a server component observed a model-API dependency: either the parsed payload or a
 * structured failure. Pages render degraded-but-honest states from this instead of crashing,
 * because a metrics outage should not take the whole story down with it.
 */
export type ResourceState<T> =
  | { status: "ready"; data: T }
  | { status: "error"; error: ModelApiErrorInfo };

export function resourceState<T>(result: PromiseSettledResult<T>): ResourceState<T> {
  if (result.status === "fulfilled") return { status: "ready", data: result.value };
  return { status: "error", error: asModelApiErrorInfo(result.reason) };
}
