import { fileURLToPath, URL } from "node:url";

import { configDefaults, defineConfig } from "vitest/config";

export default defineConfig({
  oxc: {
    jsx: {
      runtime: "automatic",
    },
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    // These node:test suites require Node's module-mock support; run test:runtime.
    exclude: [
      ...configDefaults.exclude,
      "tests/local-python-runtime.test.mjs",
      "tests/openapi-runtime-selection.test.mjs",
    ],
    fileParallelism: false,
    globals: true,
    setupFiles: "./src/test/setup.ts",
  },
});
