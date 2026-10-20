import assert from "node:assert/strict";
import { mock, test } from "node:test";
import path from "node:path";

const calls = [];
let rejected = false;
mock.module("node:child_process", {
  namedExports: { spawnSync: (...args) => { calls.push(args); return { status: 0 }; } },
});
mock.module("../local-python-runtime.mjs", {
  namedExports: { resolveLocalPython: () => {
    if (rejected) throw new Error("runtime rejected");
    return "C:\\approved\\python.exe";
  } },
});
const { generate } = await import("../openapi-ts.config.mjs");

test("runtime rejection blocks every subprocess before OpenAPI export", () => {
  rejected = true;
  assert.throws(() => generate(), /runtime rejected/);
  assert.equal(calls.length, 0);
});
test("approved runtime is used for export and check flag is retained", () => {
  rejected = false;
  generate({ check: true });
  assert.equal(calls.length, 2);
  assert.equal(calls[0][0], "C:\\approved\\python.exe");
  assert.equal(path.basename(calls[0][1][0]), "export_openapi.py");
  assert.equal(calls[1][1].at(-1), "--check");
  calls.length = 0;
  rejected = true;
  assert.throws(() => generate(), /runtime rejected/);
  assert.equal(calls.length, 0);
});
