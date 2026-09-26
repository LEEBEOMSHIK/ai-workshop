// Node filesystem imports keep the internal ledger out of client bundles.
import { readFile, realpath, stat } from "node:fs/promises";
import path from "node:path";
import { ApiError } from "../../shared/api/client";
import type { Issue, IssueLedger } from "./types";

const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(item => typeof item === "string");
const object = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null;
function issue(value: unknown): value is Issue {
  if (!object(value)) return false;
  return ["id", "title", "area", "symptom", "cause", "resolution"].every(key => typeof value[key] === "string")
    && ["open", "implemented", "verified"].includes(String(value.status))
    && ["verification", "remaining", "evidence", "commits"].every(key => strings(value[key]))
    && Array.isArray(value.history) && value.history.every(event => object(event) && typeof event.date === "string" && typeof event.event === "string");
}

export function parseIssueLedger(value: unknown): IssueLedger {
  if (!object(value) || value.schema_version !== 1 || value.visibility !== "internal" || typeof value.updated_at !== "string"
    || !Array.isArray(value.issues) || !value.issues.every(issue)
    || new Set(value.issues.map(item => item.id)).size !== value.issues.length) {
    throw new ApiError("Issue history is unavailable.", 503, "issue_history_invalid");
  }
  return value as unknown as IssueLedger;
}

async function readRepositoryFile(relative: string): Promise<string> {
  if (process.env.AI_WORKSHOP_FRONTEND_RUNTIME === "public") throw new ApiError("Not found.", 404, "not_found");
  // The Next server is launched from frontend/, like the existing dev/start commands.
  const root = path.resolve(process.cwd(), "..");
  const target = path.resolve(root, relative);
  try {
    const resolved = await realpath(target);
    if (path.relative(target, resolved) !== "" || (await stat(resolved)).size > 512 * 1024) throw new Error("Invalid file");
    return await readFile(resolved, "utf8");
  } catch {
    throw new ApiError("Issue history is unavailable.", 503, "issue_history_unavailable");
  }
}

export async function loadIssueLedger(): Promise<IssueLedger> {
  const content = await readRepositoryFile("docs/issues/issues.json");
  try { return parseIssueLedger(JSON.parse(content)); }
  catch { throw new ApiError("Issue history is unavailable.", 503, "issue_history_invalid"); }
}

export async function loadIssueDocument(ledger: IssueLedger, issueId: string, index: string): Promise<{name: string; content: string}> {
  const entry = ledger.issues.find(item => item.id === issueId);
  if (!entry || !/^(0|[1-9]\d*)$/.test(index)) throw new ApiError("Not found.", 404, "not_found");
  const name = entry.evidence[Number(index)];
  if (!name || (name !== "WORKBOARD.md" && !/^docs\/[a-zA-Z0-9_./-]+\.md$/.test(name))
    || name.split("/").includes("..")) throw new ApiError("Not found.", 404, "not_found");
  return {name, content: await readRepositoryFile(name)};
}
