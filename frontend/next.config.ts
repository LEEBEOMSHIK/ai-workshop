import path from "node:path";

import { loadEnvConfig } from "@next/env";
import type { NextConfig } from "next";

import { resolveApiTarget } from "./src/shared/config/api-target";

loadEnvConfig(path.resolve(process.cwd(), ".."));
const apiTarget = resolveApiTarget(process.env.API_PORT);

const nextConfig: NextConfig = {
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
