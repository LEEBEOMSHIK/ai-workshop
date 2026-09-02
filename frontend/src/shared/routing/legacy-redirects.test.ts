import { legacyRedirects } from "./legacy-redirects";

describe("legacy Next.js redirects", () => {
  it("permanently maps every former SPA route to its canonical access area", () => {
    expect(legacyRedirects).toEqual([
      { source: "/workspaces", destination: "/app/workspaces", permanent: true },
      {
        source: "/workspaces/:workspaceId/documents",
        destination: "/app/workspaces/:workspaceId/documents",
        permanent: true,
      },
      { source: "/rag/search", destination: "/app/rag/search", permanent: true },
      {
        source: "/rag/configurations",
        destination: "/app/rag/configurations",
        permanent: true,
      },
      {
        source: "/rag/sources/:assetVersionId",
        destination: "/app/rag/sources/:assetVersionId",
        permanent: true,
      },
      { source: "/rag/models", destination: "/admin/rag/models", permanent: true },
    ]);
  });
});
