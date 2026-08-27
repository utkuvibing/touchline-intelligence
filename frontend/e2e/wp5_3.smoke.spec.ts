import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";

const webUrl = process.env.TOUCHLINE_SMOKE_WEB_URL;
const apiUrl = process.env.TOUCHLINE_SMOKE_API_URL;
const expectedHead = process.env.TOUCHLINE_SMOKE_EXPECTED_HEAD;

function required(value: string | undefined, name: string): string {
  if (!value) throw new Error(`${name} is required for the release smoke`);
  return value.replace(/\/$/, "");
}

test("release smoke is bound to final HEAD", async ({ page }, testInfo) => {
  const repositoryRoot = execFileSync("git", ["rev-parse", "--show-toplevel"], {
    encoding: "utf8",
  }).trim();
  const actualHead = execFileSync("git", ["rev-parse", "HEAD"], {
    cwd: repositoryRoot,
    encoding: "utf8",
  }).trim();
  const workingTree = execFileSync(
    "git",
    ["status", "--porcelain=v1", "--untracked-files=all"],
    { cwd: repositoryRoot, encoding: "utf8" },
  ).trim();
  const finalHead = required(expectedHead, "TOUCHLINE_SMOKE_EXPECTED_HEAD");
  const web = required(webUrl, "TOUCHLINE_SMOKE_WEB_URL");
  const api = required(apiUrl, "TOUCHLINE_SMOKE_API_URL");
  expect(actualHead).toBe(finalHead);
  expect(workingTree).toBe("");
  await testInfo.attach("final-head-evidence.json", {
    body: JSON.stringify(
      { final_head: finalHead, observed_head: actualHead, web_url: web, api_url: api },
      null,
      2,
    ),
    contentType: "application/json",
  });

  await page.goto(`${web}/`);
  await expect(
    page.getByRole("heading", { name: /shot quality from open event data/i }),
  ).toBeVisible();

  await page.goto(`${web}/model`);
  await expect(page.getByRole("heading", { name: /what is being served/i })).toBeVisible();
  await expect(page.getByText(/not statsbomb's proprietary xg model/i)).toBeVisible();

  await page.goto(`${web}/explore`);
  await expect(
    page.getByRole("heading", { name: /world cup 2022, shot by shot/i }),
  ).toBeVisible();
  // The gate stays visible and the page stays useful around it.
  await expect(page.getByText(/publication closed/i)).toBeVisible();
  await expect(page.getByText(/recorded source facts only/i)).toBeVisible();
  await expect(
    page.getByRole("heading", { name: /the recorded tournament/i }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: /ask the model about a hypothetical shot/i })).toBeVisible();
  await expect(page.getByLabel("Hypothetical body part")).toBeVisible();

  const prediction = await page.evaluate(async ({ endpoint }) => {
    const response = await fetch(`${endpoint}/model/predict`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        location_x: 102,
        location_y: 40,
        body_part: "Right Foot",
        technique: "Normal",
        play_pattern: "Regular Play",
      }),
    });
    return { status: response.status, body: await response.json() };
  }, { endpoint: api });
  expect(prediction.status).toBe(200);
  expect(prediction.body.calibrated_probability).toBeGreaterThanOrEqual(0);
  expect(prediction.body.calibrated_probability).toBeLessThanOrEqual(1);

  const invalidPrediction = await page.evaluate(async ({ endpoint }) => {
    const response = await fetch(`${endpoint}/model/predict`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        location_x: -1,
        location_y: 40,
        body_part: "Right Foot",
        technique: "Normal",
        play_pattern: "Regular Play",
      }),
    });
    return { status: response.status, body: await response.json() };
  }, { endpoint: api });
  expect(invalidPrediction.status).toBe(422);
  expect(invalidPrediction.body.error.code).toBe("request_validation_error");

  const gate = await page.evaluate(async ({ endpoint }) => {
    const response = await fetch(`${endpoint}/model/shots`);
    return { status: response.status, body: await response.json() };
  }, { endpoint: api });
  expect(gate.status).toBe(403);
  expect(gate.body.error.code).toBe("publication_gate_closed");
});

test("playground request body, API probability, and displayed value agree byte-exact", async ({ page }) => {
  const web = required(webUrl, "TOUCHLINE_SMOKE_WEB_URL");
  const api = required(apiUrl, "TOUCHLINE_SMOKE_API_URL");

  /**
   * One unreproduced observation, recorded here on purpose: a single manual run of this
   * exact flow once displayed 4.5% for the fixed input below. Every traced reproduction
   * since (five) sent the byte-exact body asserted here and displayed the API's value
   * (3.3% at the time of writing), and no input on the served probability surface produces
   * 4.5% (14 combinations probed). Treated as an unreproduced anomaly, not a confirmed
   * bug; this test is the tripwire if it ever recurs. No workaround was added anywhere.
   */
  const input = {
    location_x: 94.5,
    location_y: 36,
    body_part: "Left Foot",
    technique: "Volley",
    play_pattern: "Regular Play",
  };

  // The API's own answer for this exact input, fetched independently of the UI. The
  // released model is deterministic, so one input always maps to one probability.
  // Runs after page.goto: an evaluate on about:blank has a null origin, which the API's
  // CORS allow-list rightly refuses.
  await page.goto(`${web}/explore`, { waitUntil: "networkidle" });
  const direct = await page.evaluate(async ({ endpoint, body }) => {
    const response = await fetch(`${endpoint}/model/predict`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`predict responded ${response.status}`);
    return (await response.json()) as { calibrated_probability: number };
  }, { endpoint: api, body: input });

  // What the page actually puts on the wire for the same input.
  const requestBodies: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/model/predict")) requestBodies.push(request.postData() ?? "");
  });

  await page.getByLabel("Hypothetical location X (0–120)").fill(String(input.location_x));
  await page.getByLabel("Hypothetical location Y (0–80)").fill(String(input.location_y));
  await page.getByLabel("Hypothetical body part").selectOption(input.body_part);
  await page.getByLabel("Hypothetical technique").selectOption(input.technique);
  await page.getByRole("button", { name: /calculate probability/i }).click();
  await page.waitForSelector(".probability-callout", { timeout: 20_000 });

  // Byte-exact request: the constructed input goes on the wire verbatim, exactly once.
  expect(requestBodies).toHaveLength(1);
  expect(requestBodies[0]).toBe(JSON.stringify(input));

  // The displayed probability is the API's answer for that exact body, never a UI-side number.
  const displayed = await page.locator(".playground-callout strong").innerText();
  expect(displayed).toBe(`${(direct.calibrated_probability * 100).toFixed(1)}%`);

  // The result only renders after the page verified the response's artifact identity.
  await expect(page.locator(".playground-result .provenance-check")).toBeVisible();
});
