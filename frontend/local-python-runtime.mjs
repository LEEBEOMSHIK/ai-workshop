import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const descriptorSha256 = "1a233b5d84a35b7df0dba52ae1beb77023799f1aa00a18445c2eef0bbbac67c4";
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const normalize = (value) => path.win32.normalize(value).replace(/[\\/]+$/, "").toLowerCase();

function ordinaryPath(value, fileSystem) {
  for (let current = value; ;) {
    // Node exposes junctions/symlinks and resolved redirection, but not every
    // Windows reparse tag. The PowerShell launcher checks all ReparsePoint tags.
    if (fileSystem.lstatSync(current).isSymbolicLink() ||
        normalize(fileSystem.realpathSync(current)) !== normalize(current)) {
      throw new Error("Approved Python runtime path contains a redirect.");
    }
    const parent = path.win32.dirname(current);
    if (parent === current) break;
    current = parent;
  }
}

export function resolveLocalPython({
  repositoryRoot: root = repositoryRoot,
  platform = process.platform,
  env = process.env,
  fileSystem = fs,
  hash = sha256,
} = {}) {
  if (platform !== "win32") return path.posix.join(root, "backend/.venv/bin/python");
  const descriptorPath = path.win32.join(root, "scripts/local_python_runtime.json");
  ordinaryPath(descriptorPath, fileSystem);
  const descriptorStat = fileSystem.lstatSync(descriptorPath);
  if (!descriptorStat.isFile() || descriptorStat.size > 4096) {
    throw new Error("Invalid approved Python descriptor file.");
  }
  const descriptorBytes = fileSystem.readFileSync(descriptorPath);
  // A different prefix/binary requires a reviewed change, never a config override.
  if (hash(descriptorBytes) !== descriptorSha256) throw new Error("Approved Python descriptor hash mismatch.");
  const descriptor = JSON.parse(descriptorBytes.toString("utf8"));
  if (descriptor.schema !== 1 || descriptor.executable !== "python.exe" ||
      !path.win32.isAbsolute(descriptor.prefix)) throw new Error("Invalid approved Python descriptor.");
  if (Object.keys(env).some((key) => key.toUpperCase() === "PYTHONHOME")) {
    throw new Error("PYTHONHOME must be unset for the approved runtime.");
  }
  if (!env.CONDA_PREFIX || !path.win32.isAbsolute(env.CONDA_PREFIX) ||
      normalize(env.CONDA_PREFIX) !== normalize(descriptor.prefix)) {
    throw new Error("Activate the approved Conda environment before running this tool.");
  }
  const metadata = path.win32.join(descriptor.prefix, "conda-meta");
  ordinaryPath(metadata, fileSystem);
  if (!fileSystem.lstatSync(metadata).isDirectory()) throw new Error("Approved runtime is not a Conda environment.");
  const executable = path.win32.join(descriptor.prefix, descriptor.executable);
  ordinaryPath(executable, fileSystem);
  const executableStat = fileSystem.lstatSync(executable);
  if (!executableStat.isFile() || executableStat.size > 32 * 1024 * 1024) throw new Error("Invalid approved Python executable.");
  if (hash(fileSystem.readFileSync(executable)) !== descriptor.sha256) throw new Error("Approved Python executable hash mismatch.");
  return executable;
}
