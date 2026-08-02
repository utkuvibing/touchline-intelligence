import { describe, expect, it } from "vitest";

import {
  ApiBaseNotConfiguredError,
  LOCAL_API_BASE,
  failureDetail,
  resolveApiBase,
} from "./api";

/**
 * These protect how the deployed frontend decides where the API is, and what it tells the reader
 * when a request fails. Both were implicated in a production outage that took far longer to
 * diagnose than it should have: the page said "/baseline responded 503" and nothing else, which
 * is true, unactionable, and indistinguishable from half a dozen unrelated causes.
 */
describe("API base resolution", () => {
  it("uses the configured origin", () => {
    expect(resolveApiBase("https://api.example.com", "production")).toBe(
      "https://api.example.com",
    );
  });

  it("strips a trailing slash so paths do not double up", () => {
    // `https://api.example.com/` + `/baseline` is `https://api.example.com//baseline`, which some
    // hosts answer and some 404 — a difference that only shows up in deployment.
    expect(resolveApiBase("https://api.example.com/", "production")).toBe(
      "https://api.example.com",
    );
    expect(resolveApiBase("https://api.example.com///", "production")).toBe(
      "https://api.example.com",
    );
  });

  it("ignores surrounding whitespace, which a pasted dashboard value carries", () => {
    expect(resolveApiBase("  https://api.example.com  ", "production")).toBe(
      "https://api.example.com",
    );
  });

  it("falls back to localhost in development, where that is the right guess", () => {
    expect(resolveApiBase(undefined, "development")).toBe(LOCAL_API_BASE);
    expect(resolveApiBase(undefined, "test")).toBe(LOCAL_API_BASE);
  });

  it.each([undefined, "", "   "])(
    "fails loudly rather than defaulting to localhost in production (%p)",
    (configured) => {
      // Missing configuration must not disguise itself as a backend outage. A deployed page
      // quietly fetching 127.0.0.1 reports that the API could not be reached, which sends the
      // reader to inspect a service that is entirely healthy.
      expect(() => resolveApiBase(configured, "production")).toThrow(ApiBaseNotConfiguredError);
      expect(() => resolveApiBase(configured, "production")).toThrow(/NEXT_PUBLIC_API_BASE/);
    },
  );
});

describe("failure detail", () => {
  function jsonResponse(body: unknown): Response {
    return new Response(JSON.stringify(body), {
      status: 503,
      headers: { "content-type": "application/json" },
    });
  }

  it("surfaces the API's own explanation", async () => {
    const detail = await failureDetail(
      jsonResponse({ detail: "database schema is behind this build" }),
    );

    expect(detail).toBe("database schema is behind this build");
  });

  it("returns null for a body that carries no explanation", async () => {
    expect(await failureDetail(jsonResponse({ error: "nope" }))).toBeNull();
    expect(await failureDetail(jsonResponse({ detail: "  " }))).toBeNull();
  });

  it("returns null rather than throwing on a non-JSON error page", async () => {
    // A proxy or edge error is HTML. Letting that parse failure escape would replace a useful
    // "the API returned 503" with an unrelated JSON syntax error.
    const html = new Response("<html>502 Bad Gateway</html>", { status: 502 });

    expect(await failureDetail(html)).toBeNull();
  });

  it("truncates, so an unexpected payload cannot flood the page", async () => {
    const detail = await failureDetail(jsonResponse({ detail: "x".repeat(1000) }));

    expect(detail).toHaveLength(300);
  });
});
