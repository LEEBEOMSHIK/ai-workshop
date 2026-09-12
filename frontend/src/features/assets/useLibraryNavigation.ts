"use client";

import { useEffect } from "react";

import { workspaceLibraryPath } from "../../shared/routing/routes";

export interface LibrarySelection {
  workspaceId?: string | null;
  folderId: string | null;
  documentId: string | null;
  versionId: string | null;
}

export type LibraryPathBuilder = (workspaceId: string, selection: LibrarySelection) => string;

export function readLibrarySelection(search: string, includeWorkspace = false): LibrarySelection {
  const query = new URLSearchParams(search);
  return {
    ...(includeWorkspace ? { workspaceId: query.get("workspace") } : {}),
    folderId: query.get("folder"),
    documentId: query.get("document"),
    versionId: query.get("version"),
  };
}

export function writeLibrarySelection(
  workspaceId: string,
  selection: LibrarySelection,
  buildPath: LibraryPathBuilder = workspaceLibraryPath,
): void {
  window.history.pushState(null, "", buildPath(workspaceId, selection));
}

export function useLibraryPopState(
  onRestore: (selection: LibrarySelection) => void,
  readSelection: (search: string) => LibrarySelection = readLibrarySelection,
  enabled = true,
): void {
  useEffect(() => {
    if (!enabled) return;
    const restore = () => onRestore(readSelection(window.location.search));
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, [enabled, onRestore, readSelection]);
}
