import { legacyRedirects } from "./legacy-redirects";

describe("legacy Next.js redirects", () => {
  it("permanently maps every former SPA route to its canonical access area", () => {
    expect(legacyRedirects).toEqual([
      { source: "/app", destination: "/workshop/workspaces", permanent: true },
      {
        source: "/app/workspaces",
        destination: "/workshop/workspaces",
        permanent: true,
      },
      {
        source: "/app/workspaces/:workspaceId/documents",
        destination: "/workshop/workspaces/:workspaceId/documents",
        permanent: true,
      },
      {
        source: "/app/rag/search",
        destination: "/workshop/rag/search",
        permanent: true,
      },
      {
        source: "/app/rag/configurations",
        destination: "/admin/rag/configurations",
        permanent: true,
      },
      {
        source: "/app/rag/sources/:assetVersionId",
        destination: "/workshop/rag/sources/:assetVersionId",
        permanent: true,
      },
      {
        source: "/workspaces",
        destination: "/workshop/workspaces",
        permanent: true,
      },
      {
        source: "/workspaces/:workspaceId/documents",
        destination: "/workshop/workspaces/:workspaceId/documents",
        permanent: true,
      },
      {
        source: "/rag/search",
        destination: "/workshop/rag/search",
        permanent: true,
      },
      {
        source: "/rag/configurations",
        destination: "/admin/rag/configurations",
        permanent: true,
      },
      {
        source: "/rag/sources/:assetVersionId",
        destination: "/workshop/rag/sources/:assetVersionId",
        permanent: true,
      },
      { source: "/rag/models", destination: "/admin/rag/models", permanent: true },
    ]);
  });
});
