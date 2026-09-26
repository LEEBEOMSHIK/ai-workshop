import { beforeEach, expect, it, vi } from "vitest";
import { serverApiRequest } from "../../shared/api/server-client";
import { loadIssueLedger, loadIssueDocument } from "./server-ledger";
vi.mock("../../shared/api/server-client", () => ({ serverApiRequest: vi.fn() }));
vi.mock("../../shared/auth/server-session", () => ({ incomingCookieHeader: vi.fn(async () => "session=existing") }));
beforeEach(() => vi.resetAllMocks());
it("loads filtered database issues with the incoming session", async () => {
    vi.mocked(serverApiRequest).mockResolvedValueOnce({ items: [], total: 0, status_counts: { open: 0, implemented: 0, verified: 0 } }).mockResolvedValueOnce({ items: [] });
    const data = await loadIssueLedger({ q: "지급일", offset: 20 });
    expect(data.list.total).toBe(0);
    expect(serverApiRequest).toHaveBeenCalledWith(expect.stringContaining("offset=20"), {}, "session=existing");
});
it("reads the exact linked document version instead of a file", async () => {
    vi.mocked(serverApiRequest).mockResolvedValue({ content: "stored database text", version: 2 });
    expect(await loadIssueDocument("issue", "doc", "2")).toEqual({ content: "stored database text", version: 2 });
    expect(serverApiRequest).toHaveBeenCalledWith("/api/v1/admin/issue-history/issues/issue/documents/doc/versions/2", {}, "session=existing");
});
