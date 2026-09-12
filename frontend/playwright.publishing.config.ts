import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`publishing_acceptance_env_missing:${name}`);
  return value;
}

function isolatedLoopbackOrigin(name: string, forbiddenPorts: readonly string[]): string {
  const value = requiredEnvironment(name);
  const url = new URL(value);
  if (
    url.protocol !== "http:" ||
    url.hostname !== "127.0.0.1" ||
    !url.port ||
    forbiddenPorts.includes(url.port) ||
    url.pathname !== "/" ||
    url.search ||
    url.hash
  ) {
    throw new Error(`publishing_acceptance_origin_not_isolated:${name}`);
  }
  return url.origin;
}

const baseURL = isolatedLoopbackOrigin("PUBLISHING_TEST_BASE_URL", ["5173"]);
const publicOnlyBaseURL = isolatedLoopbackOrigin("PUBLISHING_TEST_PUBLIC_ONLY_BASE_URL", ["5173"]);
const privateOrigin = isolatedLoopbackOrigin("PUBLISHING_TEST_PRIVATE_ORIGIN", ["18000"]);
const publicOrigin = isolatedLoopbackOrigin("PUBLISHING_TEST_PUBLIC_ORIGIN", ["18001"]);
if (new Set([baseURL, publicOnlyBaseURL, privateOrigin, publicOrigin]).size !== 4) {
  throw new Error("publishing_acceptance_origins_not_distinct");
}
const email = requiredEnvironment("PUBLISHING_TEST_EMAIL");
if (!/^[^@\s]+@example\.com$/iu.test(email)) {
  throw new Error("publishing_acceptance_email_not_reserved");
}
requiredEnvironment("PUBLISHING_TEST_PASSWORD");
requiredEnvironment("PUBLISHING_TEST_SLUG");
requiredEnvironment("PUBLISHING_TEST_PUBLIC_STORE");
requiredEnvironment("PUBLISHING_TEST_PYTHON");

export default defineConfig({
  testDir: "./tests/publishing",
  testMatch: "**/*.e2e.ts",
  outputDir: resolve(
    process.cwd(),
    "../.local-data/project-agent-work/publishing-service/task-4-output",
  ),
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180_000,
  reporter: "list",
  use: {
    baseURL,
    channel: "msedge",
    viewport: { width: 1440, height: 900 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
});
