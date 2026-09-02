import path from "node:path";
import { fileURLToPath } from "node:url";

import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";

import { resolveApiTarget } from "./src/shared/config/api-target";
import { legacyRedirects } from "./src/shared/routing/legacy-redirects";

const frontendRoot = path.dirname(fileURLToPath(import.meta.url));
const { combinedEnv } = loadEnvConfig(
  path.resolve(frontendRoot, ".."),
  process.env.NODE_ENV !== "production",
  undefined,
  true,
);
const apiTarget = resolveApiTarget(combinedEnv.API_PORT);

const nextConfig: NextConfig = {
  agentRules: false,
  env: {
    AI_WORKSHOP_API_TARGET: apiTarget,
  },
  async redirects() {
    return legacyRedirects;
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiTarget}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
