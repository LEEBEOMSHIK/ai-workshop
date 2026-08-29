import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import process from "node:process";

const frontendRoot = path.dirname(fileURLToPath(import.meta.url));
const backendRoot = path.resolve(frontendRoot, "../backend");
const python = path.join(
  backendRoot,
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
const openapiTypescript = path.join(
  frontendRoot,
  "node_modules",
  "openapi-typescript",
  "bin/cli.js",
);

export const input = path.join(backendRoot, "build/openapi.json");
export const output = path.join(frontendRoot, "src/shared/api/schema.d.ts");

function run(command, args) {
  const result = spawnSync(command, args, {
    cwd: frontendRoot,
    stdio: "inherit",
  });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}

export function generate({ check = false } = {}) {
  run(python, [path.join(backendRoot, "tools/export_openapi.py")]);
  run(process.execPath, [
    openapiTypescript,
    input,
    "--output",
    output,
    "--alphabetize",
    ...(check ? ["--check"] : []),
  ]);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  generate({ check: process.argv.includes("--check") });
}
