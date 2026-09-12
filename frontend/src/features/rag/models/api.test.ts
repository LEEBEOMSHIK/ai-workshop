import { afterEach, expect, it, vi } from "vitest";
import { approveCodexEvidence, loadModelLab, revokeCodexEvidence } from "./api";

afterEach(() => vi.unstubAllGlobals());
it("loads document processing profiles in workflow order without mutation", async () => {
  const processing = { id: "processing-v1", kind: "document_processing", name: "synthetic-processing" };
  const fetcher = vi.fn(async (input: RequestInfo | URL) => Response.json(input === "/api/v1/rag/profiles/document_processing" ? [processing] : []));
  vi.stubGlobal("fetch", fetcher);
  expect((await loadModelLab()).profiles).toEqual([processing]);
  expect(fetcher.mock.calls.map(([url]) => url)).toEqual(["/api/v1/rag/models", "/api/v1/rag/profiles/document_processing", "/api/v1/rag/profiles/indexing", "/api/v1/rag/profiles/retrieval", "/api/v1/rag/profiles/generation"]);
});
it("does not disguise a failed document-processing load as an empty registry", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => input === "/api/v1/rag/profiles/document_processing" ? Response.json({ detail: "unavailable" }, { status: 503 }) : Response.json([])));
  await expect(loadModelLab()).rejects.toThrow();
});

it("sends approval and revocation CAS bodies as JSON", async () => {
  const fetcher = vi.fn<typeof fetch>(async () => new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetcher);
  await approveCodexEvidence("revision/id", {
    classification: "public",
    content_sha256: "a".repeat(64),
    expected_generation: 2,
    request_id: "11111111-1111-4111-8111-111111111111",
  });
  await revokeCodexEvidence("revision/id", {
    expected_generation: 3,
    request_id: "22222222-2222-4222-8222-222222222222",
  });
  expect(fetcher.mock.calls.map(([path, init]) => [path, init?.method, JSON.parse(String(init?.body))])).toEqual([
    ["/api/v1/admin/rag/codex-evidence/revision%2Fid/approval", "POST", {
      classification: "public",
      content_sha256: "a".repeat(64),
      expected_generation: 2,
      request_id: "11111111-1111-4111-8111-111111111111",
    }],
    ["/api/v1/admin/rag/codex-evidence/revision%2Fid/approval", "DELETE", {
      expected_generation: 3,
      request_id: "22222222-2222-4222-8222-222222222222",
    }],
  ]);
});
