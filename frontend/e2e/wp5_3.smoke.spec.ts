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
    page.getByRole("heading", { name: /the 2022 calibration set, shot by shot/i }),
  ).toBeVisible();
  await expect(page.getByText(/publication closed/i)).toBeVisible();

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
