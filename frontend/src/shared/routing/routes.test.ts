import {
  loginPath,
  ragSourcePath,
  routes,
  workspaceDocumentPath,
} from "./routes";

describe("canonical frontend routes", () => {
  it("separates public, workshop, and administration URLs", () => {
    expect(routes).toMatchObject({
      home: "/",
      labs: "/labs",
      ragLab: "/labs/rag",
      workshopHome: "/workshop/workspaces",
      workshopRagSearch: "/workshop/rag/search",
      adminRagConfigurations: "/admin/rag/configurations",
      adminRagModels: "/admin/rag/models",
    });
  });

  it("encodes dynamic path segments and login return paths", () => {
    expect(workspaceDocumentPath("space/id")).toBe(
      "/workshop/workspaces/space%2Fid/documents",
    );
    expect(ragSourcePath("asset/id")).toBe(
      "/workshop/rag/sources/asset%2Fid",
    );
    expect(loginPath(routes.workshopRagSearch)).toBe(
      "/login?next=%2Fworkshop%2Frag%2Fsearch",
    );
  });
});
