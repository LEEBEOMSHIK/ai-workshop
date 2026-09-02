import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

import { resolveApiTarget } from "./src/app/apiTarget.ts";

export default defineConfig(({ mode }) => {
  const environment = loadEnv(mode, "..", "");
  return {
    envDir: "..",
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        "/api": resolveApiTarget(environment.API_PORT),
      },
    },
    test: {
      environment: "jsdom",
      fileParallelism: false,
      globals: true,
      setupFiles: "./src/test/setup.ts",
    },
  };
});
