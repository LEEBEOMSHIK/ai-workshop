import { ApiError } from "../../shared/api/client";
import type { DocumentMoveResult, DocumentSummary, FolderMoveResult, FolderSummary, LibraryPage } from "./api";

export type MoveSource = { kind: "document" | "folder"; id: string; workspaceId: string; name: string; parentId: string | null; revision: number };
export type MoveResult = DocumentMoveResult | FolderMoveResult;
export const MOVE_MIME = "application/x-ai-workshop-asset-move";

export function hasMoveRevision(revision: unknown): revision is number {
  return typeof revision === "number" && Number.isSafeInteger(revision) && revision > 0;
}

export function documentMoveSource(document: DocumentSummary): MoveSource | null {
  return hasMoveRevision(document.metadata_revision) ? { kind: "document", id: document.id, workspaceId: document.workspace_id, name: document.name, parentId: document.folder_id, revision: document.metadata_revision } : null;
}

export function folderMoveSource(folder: FolderSummary, workspaceId: string): MoveSource | null {
  return hasMoveRevision(folder.metadata_revision) ? { kind: "folder", id: folder.id, workspaceId, name: folder.name, parentId: folder.parent_id, revision: folder.metadata_revision } : null;
}

export function moveDestinationProblem(source: MoveSource, page: LibraryPage | null): string | null {
  if (!page) return "목적지를 확인하는 중입니다.";
  if (page.workspace.id !== source.workspaceId) return "같은 공간 안에서만 이동할 수 있습니다.";
  if (!hasMoveRevision(source.revision)) return "이동 정보를 새로 불러와 주세요.";
  if (source.kind === "folder" && [...page.ancestors, ...(page.folder ? [page.folder] : [])].some((folder) => folder.id === source.id)) return "자기 자신이나 하위 폴더로 이동할 수 없습니다.";
  if ((page.folder?.id ?? null) === source.parentId) return "이미 이 위치에 있습니다.";
  return null;
}

export function assertMoveSourceUnchanged(source: MoveSource, fresh: MoveSource | null) {
  if (!fresh || fresh.id !== source.id || fresh.workspaceId !== source.workspaceId || fresh.parentId !== source.parentId || fresh.revision !== source.revision) throw new ApiError("metadata changed", 409, "asset_revision_conflict");
}

export function movementError(failure: unknown): string {
  if (!(failure instanceof ApiError)) return "이동 결과를 확인하지 못했습니다. 목록을 새로고침해 현재 위치를 확인해 주세요.";
  const messages: Record<string, string> = {
    asset_revision_conflict: "원본 위치 또는 정보가 변경되었습니다. 이동 정보를 새로 불러온 뒤 다시 확인해 주세요.",
    folder_exists: "목적지에 같은 이름의 폴더가 있습니다. 다른 위치를 선택해 주세요.",
    folder_cycle: "자기 자신이나 하위 폴더로 이동할 수 없습니다.",
    folder_depth_exceeded: "폴더의 최대 깊이를 넘습니다. 더 상위 위치를 선택해 주세요.",
    folder_hierarchy_invalid: "폴더 구조를 확인할 수 없습니다. 관리자에게 복구를 요청해 주세요.",
    not_found: "원본 또는 목적지에 접근할 수 없습니다. 권한을 다시 확인해 주세요.",
  };
  return messages[failure.code] ?? ([401, 403, 404].includes(failure.status) ? "원본 또는 목적지에 접근할 수 없습니다. 권한을 다시 확인해 주세요." : "이동하지 못했습니다. 이동 정보를 새로 불러온 뒤 다시 확인해 주세요.");
}
