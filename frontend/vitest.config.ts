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
    // Run node:test suites with test:runtime or test:styles, outside jsdom/Vite.
    exclude: [
      ...configDefaults.exclude,
      "tests/local-python-runtime.test.mjs",
      "tests/openapi-runtime-selection.test.mjs",
      "tests/ui-style/design-tokens.test.mjs",
    ],
    fileParallelism: false,
    globals: true,
    setupFiles: "./src/test/setup.ts",
  },
});
