import {
  loginPath,
  learningRecordPath,
  ragDomainChatPath,
  ragDomainFilesPath,
  ragSourcePath,
  publicStudyPath,
  routes,
  workspaceDocumentPath,
  workspaceLibraryPath,
} from "./routes";

describe("canonical frontend routes", () => {
  it("separates public, workshop, and administration URLs", () => {
    expect(routes).toMatchObject({
      home: "/",
      labs: "/labs",
      ragLab: "/labs/rag",
      ragStudies: "/labs/rag/studies",
      workshopHome: "/workshop/workspaces",
      workshopRagSearch: "/workshop/rag/search",
      workshopLearning: "/workshop/learning",
      adminRagDomains: "/admin/rag/domains",
      adminRagConfigurations: "/admin/rag/configurations",
      adminRagModels: "/admin/rag/models",
      adminSystemRuntime: "/admin/system/runtime",
      adminSystemAccess: "/admin/system/access",
      adminPublishing: "/admin/publishing",
    });
  });

  it("encodes dynamic path segments and login return paths", () => {
    expect(workspaceDocumentPath("space/id")).toBe(
      "/workshop/workspaces/space%2Fid/documents",
    );
    expect(ragSourcePath("asset/id")).toBe(
      "/workshop/rag/sources/asset%2Fid",
    );
    expect(ragDomainChatPath("asset/manage")).toBe(
      "/workshop/rag/domains/asset%2Fmanage/chat",
    );
    expect(ragDomainFilesPath("asset/manage")).toBe(
      "/workshop/rag/domains/asset%2Fmanage/files",
    );
    expect(learningRecordPath("record/id")).toBe(
      "/workshop/learning/record%2Fid",
    );
    expect(publicStudyPath("study/id")).toBe("/studies/study%2Fid");
    expect(loginPath(routes.workshopRagSearch)).toBe(
      "/login?next=%2Fworkshop%2Frag%2Fsearch",
    );
  });

  it("carries only bounded workspace and document UUID pairs into domain chat", () => {
    expect(ragDomainChatPath("asset-management", [
      { workspaceId: "11111111-1111-4111-8111-111111111111", documentId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" },
      { workspaceId: "22222222-2222-4222-8222-222222222222", documentId: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb" },
    ])).toBe(
      "/workshop/rag/domains/asset-management/chat?selected=11111111-1111-4111-8111-111111111111%3Aaaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa&selected=22222222-2222-4222-8222-222222222222%3Abbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    );
    expect(ragDomainFilesPath("asset-management", {
      workspaceId: "11111111-1111-4111-8111-111111111111",
      folderId: "folder/id",
      documentId: "document/id",
      versionId: "version/id",
    })).toBe(
      "/workshop/rag/domains/asset-management/files?workspace=11111111-1111-4111-8111-111111111111&folder=folder%2Fid&document=document%2Fid&version=version%2Fid",
    );
  });

  it("encodes the exact folder, document, and version restoration query", () => {
    expect(workspaceLibraryPath("space/id", {
      folderId: "folder/id",
      documentId: "document/id",
      versionId: "version/id",
    })).toBe(
      "/workshop/workspaces/space%2Fid/documents?folder=folder%2Fid&document=document%2Fid&version=version%2Fid",
    );
    expect(workspaceLibraryPath("space/id", {})).toBe(
      "/workshop/workspaces/space%2Fid/documents",
    );
  });
});
