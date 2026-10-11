import { describe, expect, it } from "vitest";
import { flowCatalogForUser } from "./catalog";
import type { SessionUser } from "../../../../features/identity/session";

const member: SessionUser = { id: "flow-member", email: "member@example.test", display_name: "Member", role: "member" };

describe("server flow composition", () => {
  it("strips owner-only links before returning member client data", () => {
    const flows = flowCatalogForUser(member);
    expect(flows).toHaveLength(5);
    expect(flows.flatMap(flow => flow.links).some(link => link.audience === "owner" || link.href.startsWith("/admin"))).toBe(false);
    expect(flows.find(flow => flow.id === "answer")?.links.map(link => link.href)).toEqual(["/workshop/rag/search"]);
  });

  it("keeps owner monitoring links without mutating the shared catalog", () => {
    const ownerFlows = flowCatalogForUser({ ...member, role: "owner" });
    const memberFlows = flowCatalogForUser(member);
    expect(ownerFlows.find(flow => flow.id === "answer")?.links.map(link => link.href)).toContain("/admin/rag/executions");
    expect(memberFlows.find(flow => flow.id === "answer")?.links.map(link => link.href)).not.toContain("/admin/rag/executions");
  });
});
