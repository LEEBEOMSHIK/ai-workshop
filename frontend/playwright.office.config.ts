import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/office",
  testMatch: "**/*.e2e.ts",
  outputDir: "../.local-data/browser-verification/office-game",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  reporter: "list",
  use: {
    baseURL: process.env.OFFICE_TEST_BASE_URL ?? "http://127.0.0.1:5173",
    channel: process.env.OFFICE_TEST_BROWSER ?? "msedge",
    viewport: { width: 1280, height: 800 },
    trace: "retain-on-failure",
  },
});
