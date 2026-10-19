import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.CRAG_WEB_URL ?? "http://localhost:8600";

/** End-to-end specs live in tests/e2e and run against the running compose stack (`make e2e`). */
export default defineConfig({
  testDir: "../tests/e2e",
  outputDir: "../test-results",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: { baseURL, trace: "retain-on-failure" },
  projects: [
    {
      name: "e2e",
      testIgnore: /screenshots\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 860 } },
    },
    {
      name: "screenshots",
      testMatch: /screenshots\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 860 }, video: "on" },
    },
  ],
});
