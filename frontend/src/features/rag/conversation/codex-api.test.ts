import { afterEach, vi } from "vitest";
import { searchDomain, type DomainSearchRequest } from "./api";
import { searchEvidence, type SearchRequest } from "../search/api";

afterEach(() => vi.unstubAllGlobals());
it("adds a browser mutation marker only for attested Codex search requests", async () => {
  const fetcher = vi.fn<typeof fetch>(async () => new Response("{}", { headers: { "content-type": "application/json" } }));
  vi.stubGlobal("fetch", fetcher);
  const approval = { classification: "synthetic" as const, consented: true, disclosure_version: "codex-external-generation-v1" };
  const domainRequest: DomainSearchRequest = { connection_version_id: "connection", query: "Synthetic question", workspace_ids: ["workspace"], top_k: 10 };
  const searchRequest: SearchRequest = { configuration_id: "configuration", query: "Synthetic question", workspace_ids: ["workspace"], top_k: 10, experimental: false };
  await searchDomain("test", domainRequest);
  await searchDomain("test", { ...domainRequest, codex_input_approval: approval });
  await searchEvidence(searchRequest);
  await searchEvidence({ ...searchRequest, codex_input_approval: approval });
  for (const index of [0, 2]) expect(new Headers(fetcher.mock.calls[index][1]?.headers).has("x-codex-request")).toBe(false);
  for (const index of [1, 3]) {
    const headers = new Headers(fetcher.mock.calls[index][1]?.headers);
    expect(headers.get("x-codex-request")).toBe("1");
    expect(headers.get("content-type")).toBe("application/json");
    expect(headers.has("Origin")).toBe(false);
  }
});
