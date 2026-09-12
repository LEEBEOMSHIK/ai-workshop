import path from "node:path";
import { fileURLToPath } from "node:url";

import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";

import { resolveApiTarget } from "./src/shared/config/api-target";
import {
  decideFrontendRuntime,
  resolveFrontendDistDir,
  resolvePublicApiTarget,
} from "./src/shared/config/public-runtime";
import { legacyRedirects } from "./src/shared/routing/legacy-redirects";

const frontendRoot = path.dirname(fileURLToPath(import.meta.url));
const runtime = decideFrontendRuntime(process.env.AI_WORKSHOP_FRONTEND_RUNTIME);
const distDir = resolveFrontendDistDir(process.env.AI_WORKSHOP_FRONTEND_INSTANCE);
const combinedEnv = runtime.loadRootEnvironment
  ? loadEnvConfig(
      path.resolve(frontendRoot, ".."),
      process.env.NODE_ENV !== "production",
      undefined,
      true,
    ).combinedEnv
  : process.env;
const apiTarget = runtime.allowPrivateRoutes
  ? resolveApiTarget(combinedEnv.API_PORT)
  : undefined;
const publicApiTarget = resolvePublicApiTarget(combinedEnv);

const nextConfig: NextConfig = {
  agentRules: false,
  ...(distDir ? { distDir } : {}),
  env: {
    ...(apiTarget ? { AI_WORKSHOP_API_TARGET: apiTarget } : {}),
    AI_WORKSHOP_FRONTEND_RUNTIME: runtime.mode,
    AI_WORKSHOP_PUBLIC_API_TARGET: publicApiTarget,
  },
  async redirects() {
    return legacyRedirects;
  },
  async rewrites() {
    return [
      {
        source: "/api/public/:path*",
        destination: `${publicApiTarget}/api/public/:path*`,
      },
      ...(apiTarget ? [{
        source: "/api/:path*",
        destination: `${apiTarget}/api/:path*`,
      }] : []),
    ];
  },
};

export default nextConfig;
