import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTypescript,
  {
    files: ["src/**/SourceViewer.tsx"],
    rules: {
      "@next/next/no-img-element": "off",
    },
  },
  globalIgnores([".next/**", "coverage/**", "dist/**", "next-env.d.ts"]),
]);
