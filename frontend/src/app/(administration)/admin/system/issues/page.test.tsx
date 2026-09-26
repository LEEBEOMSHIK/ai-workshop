import { beforeEach, expect, it, vi } from "vitest";
import { requireOwner } from "../../../../../shared/auth/server-session";
import { loadIssueLedger, loadIssueDocument } from "../../../../../features/issue-history/server-ledger";
import IssueHistoryRoute from "./page";

vi.mock("../../../../../features/issue-history/IssueHistoryPage", () => ({IssueHistoryPage: vi.fn(() => null)}));
vi.mock("../../../../../features/issue-history/server-ledger", () => ({loadIssueLedger: vi.fn(), loadIssueDocument: vi.fn()}));
vi.mock("../../../../../shared/auth/server-session", () => ({requireOwner: vi.fn()}));
beforeEach(() => vi.resetAllMocks());

it("does not read issue history or documents when owner authorization fails", async () => {
  vi.mocked(requireOwner).mockRejectedValue(new Error("redirect"));
  await expect(IssueHistoryRoute({searchParams: Promise.resolve({issue: "TEST-1", document: "0"})})).rejects.toThrow("redirect");
  expect(loadIssueLedger).not.toHaveBeenCalled();
  expect(loadIssueDocument).not.toHaveBeenCalled();
});
it("requires owner before loading the internal history", async () => {
  vi.mocked(loadIssueLedger).mockResolvedValue({schema_version: 1, updated_at: "2026-09-27", visibility: "internal", issues: []});
  await IssueHistoryRoute({searchParams: Promise.resolve({})});
  expect(requireOwner).toHaveBeenCalledWith("/admin/system/issues");
  expect(vi.mocked(requireOwner)).toHaveBeenCalledBefore(vi.mocked(loadIssueLedger));
});
