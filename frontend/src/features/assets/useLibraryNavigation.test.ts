import { readLibrarySelection, writeLibrarySelection } from "./useLibraryNavigation";
import { vi } from "vitest";

it("optionally reads a domain workspace and writes through an injected path builder", () => {
  expect(readLibrarySelection("?workspace=workspace-2&folder=folder-1&document=document-1&version=version-1", true)).toEqual({
    workspaceId: "workspace-2",
    folderId: "folder-1",
    documentId: "document-1",
    versionId: "version-1",
  });
  const path = vi.fn(() => "/workshop/rag/domains/asset-management/files?workspace=workspace-2");
  const push = vi.spyOn(window.history, "pushState");

  writeLibrarySelection("workspace-2", { folderId: null, documentId: null, versionId: null }, path);

  expect(path).toHaveBeenCalledWith("workspace-2", { folderId: null, documentId: null, versionId: null });
  expect(push).toHaveBeenCalledWith(null, "", "/workshop/rag/domains/asset-management/files?workspace=workspace-2");
});
