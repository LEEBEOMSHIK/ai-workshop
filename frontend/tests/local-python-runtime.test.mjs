import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { resolveLocalPython } from "../local-python-runtime.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const descriptorBytes = fs.readFileSync(path.join(root, "scripts/local_python_runtime.json"));
const descriptor = JSON.parse(descriptorBytes);
const executable = path.win32.join(descriptor.prefix, descriptor.executable);
const executableBytes = Buffer.from("approved binary fixture");
const normalize = (value) => path.win32.normalize(value).toLowerCase();

function fixture() {
  const state = { descriptorBytes, executableBytes, symlink: null, redirect: null, missingMetadata: false };
  const fileSystem = {
    lstatSync(value) {
      const isFile = ["local_python_runtime.json", "python.exe"].includes(path.win32.basename(value));
      return {
        isSymbolicLink: () => normalize(value) === normalize(state.symlink ?? ""),
        isFile: () => isFile,
        isDirectory: () => !isFile && !(state.missingMetadata && value.endsWith("conda-meta")),
        size: value.endsWith("python.exe") ? state.executableBytes.length : state.descriptorBytes.length,
      };
    },
    realpathSync: (value) => normalize(value) === normalize(state.redirect ?? "") ? "C:\\redirected" : value,
    readFileSync: (value) => value.endsWith("python.exe") ? state.executableBytes : state.descriptorBytes,
  };
  const hash = (bytes) => bytes === executableBytes ? descriptor.sha256 : createHash("sha256").update(bytes).digest("hex");
  return { state, options: { repositoryRoot: root, platform: "win32", env: { CONDA_PREFIX: descriptor.prefix }, fileSystem, hash } };
}

test("Windows chooses only the reviewed executable without launching it", () => {
  const { options } = fixture();
  assert.equal(resolveLocalPython(options), executable);
});
test("POSIX retains backend .venv/bin/python and does not read Windows config", () => {
  assert.equal(resolveLocalPython({ repositoryRoot: "/project", platform: "linux", fileSystem: {} }), "/project/backend/.venv/bin/python");
});
for (const prefix of [undefined, "C:/different", "relative"]) {
  test(`rejects inactive or different Conda prefix: ${prefix}`, () => {
    const { options } = fixture();
    options.env.CONDA_PREFIX = prefix;
    assert.throws(() => resolveLocalPython(options), /Activate the approved Conda/);
  });
}
test("rejects PYTHONHOME", () => {
  const { options } = fixture();
  options.env.PYTHONHOME = "C:/another";
  assert.throws(() => resolveLocalPython(options), /PYTHONHOME/);
});
test("rejects an explicitly empty PYTHONHOME", () => {
  const { options } = fixture();
  options.env.PYTHONHOME = "";
  assert.throws(() => resolveLocalPython(options), /PYTHONHOME/);
});
test("rejects differently cased Windows PYTHONHOME", () => {
  const { options } = fixture();
  options.env.PythonHome = "";
  assert.throws(() => resolveLocalPython(options), /PYTHONHOME/);
});
test("rejects changed descriptor even if it points at another valid environment", () => {
  const { state, options } = fixture();
  state.descriptorBytes = Buffer.from(JSON.stringify({ ...descriptor, prefix: "C:/other" }));
  assert.throws(() => resolveLocalPython(options), /descriptor hash/);
});
test("rejects changed executable", () => {
  const { state, options } = fixture();
  state.executableBytes = Buffer.from("different binary");
  assert.throws(() => resolveLocalPython(options), /executable hash/);
});
test("rejects missing Conda metadata", () => {
  const { state, options } = fixture();
  state.missingMetadata = true;
  assert.throws(() => resolveLocalPython(options), /Conda environment/);
});
for (const field of ["symlink", "redirect"]) {
  test(`rejects ${field} in executable ancestors`, () => {
    const { state, options } = fixture();
    state[field] = path.win32.dirname(executable);
    assert.throws(() => resolveLocalPython(options), /redirect/);
  });
}
