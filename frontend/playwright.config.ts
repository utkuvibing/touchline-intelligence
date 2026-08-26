import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  outputDir: "../.scratch/playwright/wp5-3",
  reporter: [["list"], ["json", { outputFile: "../.scratch/playwright/wp5-3/report.json" }]],
  use: {
    baseURL: process.env.TOUCHLINE_SMOKE_WEB_URL,
    trace: "retain-on-failure",
  },
});
