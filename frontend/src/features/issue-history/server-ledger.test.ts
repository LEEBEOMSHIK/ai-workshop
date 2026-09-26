import { readFile, realpath, stat } from "node:fs/promises";
import path from "node:path";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { loadIssueDocument, loadIssueLedger, parseIssueLedger } from "./server-ledger";
import type { IssueLedger } from "./types";

vi.mock("node:fs/promises", () => {
  const methods = {readFile: vi.fn(), realpath: vi.fn(), stat: vi.fn()};
  return {...methods, default: methods};
});
const ledger: IssueLedger = {schema_version: 1, updated_at: "2026-09-27", visibility: "internal", issues: [{
  id: "TEST-1", title: "Synthetic issue", area: "test", status: "open", symptom: "symptom", cause: "cause", resolution: "pending",
  verification: [], remaining: ["verify"], evidence: ["docs/worklogs/synthetic.md"], commits: [], history: [],
}]};
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(realpath).mockImplementation(async value => String(value));
  vi.mocked(stat).mockResolvedValue({size: 100} as Awaited<ReturnType<typeof stat>>);
  vi.mocked(readFile).mockResolvedValue(JSON.stringify(ledger));
});
afterEach(() => vi.unstubAllEnvs());

it("loads the internal ledger without copying it into public assets", async () => {
  expect(await loadIssueLedger()).toEqual(ledger);
  expect(readFile).toHaveBeenCalledWith(path.resolve(process.cwd(), "../docs/issues/issues.json"), "utf8");
});
it("rejects public runtime before reading any internal data", async () => {
  vi.stubEnv("AI_WORKSHOP_FRONTEND_RUNTIME", "public");
  await expect(loadIssueLedger()).rejects.toMatchObject({status: 404});
  expect(readFile).not.toHaveBeenCalled();
});
it("rejects malformed records and duplicate issue ids", () => {
  expect(() => parseIssueLedger({...ledger, issues: [...ledger.issues, ...ledger.issues]})).toThrow();
  expect(() => parseIssueLedger({...ledger, visibility: "public"})).toThrow();
  expect(() => parseIssueLedger({...ledger, issues: [{...ledger.issues[0], status: "done"}]})).toThrow();
});
it("opens only an evidence entry belonging to the selected issue", async () => {
  vi.mocked(readFile).mockResolvedValue("# Synthetic evidence");
  expect(await loadIssueDocument(ledger, "TEST-1", "0")).toEqual({name: "docs/worklogs/synthetic.md", content: "# Synthetic evidence"});
  await expect(loadIssueDocument(ledger, "OTHER", "0")).rejects.toMatchObject({status: 404});
  await expect(loadIssueDocument(ledger, "TEST-1", "../.env")).rejects.toMatchObject({status: 404});
  await expect(loadIssueDocument({...ledger, issues: [{...ledger.issues[0], evidence: ["docs/../.env.md"]}]}, "TEST-1", "0")).rejects.toMatchObject({status: 404});
});
it("rejects symlink escapes without exposing resolved filesystem paths", async () => {
  vi.mocked(realpath).mockResolvedValue(path.resolve(process.cwd(), "../.env"));
  await expect(loadIssueDocument(ledger, "TEST-1", "0")).rejects.toMatchObject({code: "issue_history_unavailable"});
  expect(readFile).not.toHaveBeenCalled();
});
it("rejects oversized documents before reading their content", async () => {
  vi.mocked(stat).mockResolvedValue({size: 512 * 1024 + 1} as Awaited<ReturnType<typeof stat>>);
  await expect(loadIssueDocument(ledger, "TEST-1", "0")).rejects.toMatchObject({status: 503});
  expect(readFile).not.toHaveBeenCalled();
});
