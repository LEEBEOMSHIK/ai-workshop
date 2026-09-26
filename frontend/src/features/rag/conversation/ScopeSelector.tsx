import { useState } from "react";
import type { Domain } from "../domains/api";
import type { Folder } from "./api";
import type { ScopeMode, ScopeSnapshot, Selection } from "./types";
import { scopeSummary } from "./types";

export function ScopeSelector({
  domain,
  workspaceIds,
  folderIds,
  foldersByWorkspace,
  open,
  searching,
  folderError,
  mode,
  selection,
  onApplyScope,
  onToggleOpen,
}: {
  domain: Domain;
  workspaceIds: string[];
  folderIds: string[];
  foldersByWorkspace: Record<string, Folder[]>;
  open: boolean;
  searching: boolean;
  folderError: boolean;
  mode: ScopeMode;
  selection: Selection;
  onApplyScope: (mode: Exclude<ScopeMode, "documents">, workspaceIds: string[], folderIds: string[]) => void;
  onToggleOpen: () => void;
}) {
  const [draftMode, setDraftMode] = useState<Exclude<ScopeMode, "documents">>(mode === "folder" ? "folder" : "workspace");
  const [draftWorkspaceIds, setDraftWorkspaceIds] = useState(workspaceIds);
  const [draftFolderIds, setDraftFolderIds] = useState(folderIds);
  const workspaceNames = new Map(domain.workspace_options.map((workspace) => [workspace.id, workspace.name]));
  const folderEntries = Object.entries(foldersByWorkspace).flatMap(([workspaceId, folders]) =>
    folders.map((folder) => ({ workspaceId, folder })));
  if (mode === "documents" && !open) {
    return (
      <section className="conversation-scope">
        <p><strong>선택 문서만 검색</strong></p>
        <p>{scopeSummary(buildScopeSnapshot(domain, workspaceIds, [], foldersByWorkspace, selection))}</p>
        <div className="scope-controls">
          <button type="button" className="secondary-button" disabled={searching} onClick={onToggleOpen}>공간·폴더 범위로 전환</button>
        </div>
        {!selection || selection.documentIds.length === 0 ? <p role="status">선택 문서가 없습니다. 문서를 추가해야 질문을 보낼 수 있습니다.</p> : null}
      </section>
    );
  }
  return (
    <section className="conversation-scope">
      <p><strong>{mode === "documents" ? "선택 문서만 검색" : mode === "folder" ? "폴더 범위 검색" : "공간 범위 검색"}</strong></p>
      <button type="button" className="scope-toggle" aria-expanded={open} disabled={searching} onClick={onToggleOpen}>
        {open ? "검색 범위 닫기" : "검색 범위 열기"}
      </button>
      <p>{mode !== "documents" && workspaceIds.length === 0 && folderIds.length === 0 ? "검색 범위를 선택해 적용하세요." : scopeSummary(buildScopeSnapshot(domain, workspaceIds, folderIds, foldersByWorkspace, mode === "documents" ? selection : null))}</p>
      {open ? (
        <div className="scope-controls">
          <fieldset disabled={searching}>
            <legend>범위 방식</legend>
            <label><input type="radio" name="scope-mode" checked={draftMode === "workspace"} onChange={() => setDraftMode("workspace")} />공간</label>
            <label><input type="radio" name="scope-mode" checked={draftMode === "folder"} onChange={() => setDraftMode("folder")} />폴더</label>
          </fieldset>
          <fieldset disabled={searching}>
            <legend>검색할 지식 공간</legend>
            {domain.workspace_options.map((workspace) => (
              <label key={workspace.id}>
                <input type="checkbox" checked={draftWorkspaceIds.includes(workspace.id)} onChange={(event) => {
                  setDraftWorkspaceIds((current) => event.target.checked ? unique([...current, workspace.id]) : current.filter((id) => id !== workspace.id));
                  if (!event.target.checked) {
                    const workspaceFolderIds = new Set((foldersByWorkspace[workspace.id] ?? []).map(({ id }) => id));
                    setDraftFolderIds((current) => current.filter((id) => !workspaceFolderIds.has(id)));
                  }
                }} />
                {workspaceKindLabel(workspace.kind)} · {workspace.name}
              </label>
            ))}
          </fieldset>
          {draftMode === "folder" && folderEntries.length > 0 ? (
            <fieldset disabled={searching}>
              <legend>폴더로 더 좁히기</legend>
              {folderEntries.filter(({ workspaceId }) => draftWorkspaceIds.includes(workspaceId)).map(({ workspaceId, folder }) => (
                <label key={folder.id}>
                  <input type="checkbox" checked={draftFolderIds.includes(folder.id)} onChange={(event) => {
                    setDraftFolderIds((current) => event.target.checked ? unique([...current, folder.id]) : current.filter((id) => id !== folder.id));
                    if (event.target.checked) setDraftWorkspaceIds((current) => unique([...current, workspaceId]));
                  }} />
                  {workspaceNames.get(workspaceId)} / {folderPath(folder, foldersByWorkspace[workspaceId] ?? [])}
                </label>
              ))}
            </fieldset>
          ) : null}
          {draftMode === "folder" ? <p>선택한 폴더에 직접 속한 문서만 포함하며 하위 폴더는 포함하지 않습니다.</p> : null}
          <button type="button" disabled={searching} onClick={() => onApplyScope(draftMode, draftMode === "folder" ? workspaceIdsForFolders(draftFolderIds, folderEntries) : draftWorkspaceIds, draftMode === "folder" ? draftFolderIds : [])}>범위 적용</button>
          <button type="button" className="secondary-button" disabled={searching} onClick={onToggleOpen}>취소</button>
        </div>
      ) : null}
      {folderError ? <p className="form-error" role="alert">폴더 목록을 불러오지 못했습니다. 지식 공간 전체 검색은 계속 사용할 수 있습니다.</p> : null}
      {mode === "workspace" && workspaceIds.length === 0 ? <p role="status">하나 이상의 지식 공간을 선택하세요.</p> : null}
      {mode === "folder" && folderIds.length === 0 ? <p role="status">하나 이상의 폴더를 선택하세요.</p> : null}
    </section>
  );
}

function unique(values: string[]): string[] { return [...new Set(values)]; }
function workspaceIdsForFolders(folderIds: string[], entries: Array<{ workspaceId: string; folder: Folder }>): string[] {
  return unique(entries.filter(({ folder }) => folderIds.includes(folder.id)).map(({ workspaceId }) => workspaceId));
}
function folderPath(folder: Folder, folders: Folder[]): string {
  const byId = new Map(folders.map((entry) => [entry.id, entry]));
  const names = [folder.name];
  let parentId = folder.parent_id;
  const visited = new Set([folder.id]);
  while (parentId && !visited.has(parentId)) {
    visited.add(parentId);
    const parent = byId.get(parentId);
    if (!parent) break;
    names.unshift(parent.name);
    parentId = parent.parent_id;
  }
  return names.join(" / ");
}
function workspaceKindLabel(kind: Domain["workspace_options"][number]["kind"]): string {
  return { company: "회사 공간", team: "팀 공간", personal: "개인 공간", temporary: "임시 공간" }[kind];
}

export function buildScopeSnapshot(
  domain: Domain,
  workspaceIds: string[],
  folderIds: string[],
  foldersByWorkspace: Record<string, Folder[]>,
  selection: import("./types").Selection = null,
): ScopeSnapshot {
  const selectedWorkspaceIds = domain.workspace_options.filter(({ id }) => workspaceIds.includes(id)).map(({ id }) => id);
  const selectedFolders = Object.entries(foldersByWorkspace).flatMap(([workspaceId, folders]) =>
    folders.map((folder) => ({ workspaceId, folder }))).filter(
      ({ workspaceId, folder }) => selectedWorkspaceIds.includes(workspaceId) && folderIds.includes(folder.id),
    );
  return {
    workspaceIds: selectedWorkspaceIds,
    workspaceNames: selectedWorkspaceIds.flatMap((id) => {
      const name = domain.workspace_options.find((workspace) => workspace.id === id)?.name;
      return name ? [name] : [];
    }),
    folderIds,
    folderNames: folderIds.map((id) => selectedFolders.find(({ folder }) => folder.id === id)?.folder.name ?? "선택한 폴더(조회 불가)"),
    documentIds: selection?.documentIds ?? null,
    documentNames: selection?.documentNames ?? [],
    documents: selection?.documents ?? [],
  };
}
