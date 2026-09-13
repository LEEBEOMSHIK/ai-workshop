import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { DocumentSelectionPanel } from "./DocumentSelectionPanel";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

const workspaceId = "11111111-1111-4111-8111-111111111111";
const documentId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const document = { active_version_id: "version-1", folder_id: null, id: documentId, job_id: null, latest_version: 1, latest_version_id: "version-1", metadata_revision: 1, name: "운용 규정.md", status: "ready", workspace_id: workspaceId } as const;

it("contains Tab and consumes Escape in the nested move dialog without closing file selection", async () => {
  const workspace = { id: workspaceId, name: "회사 규정", kind: "company", expires_at: null };
  vi.stubGlobal("fetch", vi.fn(async (input) => {
    const path = String(input);
    if (path.endsWith("/capabilities")) return Response.json({ read: true, write: true, delete: false, manage_members: false });
    if (path.endsWith("/library")) return Response.json({ domain_id: "domain-1", display_name: "자산운용", connection_version_id: "connection-1", selection_limit: 2, workspace_options: [workspace] });
    return Response.json({ workspace, folder: null, ancestors: [], documents: [document], folders: [], next_document_cursor: null, next_folder_cursor: null });
  }));
  const close = vi.fn(); const user = userEvent.setup();
  render(<DocumentSelectionPanel slug="asset-management" currentDocuments={[document]} workspaceIds={[workspaceId]} folderIds={[]} foldersByWorkspace={{}} onApply={vi.fn()} onClose={close} returnFocus={null} />);
  const moveButton = await screen.findByRole("button", { name: "운용 규정.md 이동" });
  await waitFor(() => expect(moveButton).toBeEnabled());
  await user.click(moveButton);
  const inner = screen.getByRole("dialog", { name: "이동 확인" });
  await waitFor(() => expect(within(inner).getByRole("button", { name: "파일함 최상위" })).toBeEnabled());
  const cancel = within(inner).getByRole("button", { name: "이동 취소" });
  expect(cancel).toHaveFocus(); await user.tab();
  expect(within(inner).getByRole("button", { name: "파일함 최상위" })).toHaveFocus();
  await user.tab({ shift: true }); expect(cancel).toHaveFocus();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog", { name: "이동 확인" })).not.toBeInTheDocument();
  expect(screen.getByRole("dialog", { name: "파일 선택" })).toBeVisible(); expect(close).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "운용 규정.md 이동" })).toHaveFocus();
});

it("places initial focus inside the modal and contains forward and reverse Tab navigation", async () => {
  stubRootLibrary();
  const opener = documentNode("button");
  opener.focus();
  const user = userEvent.setup();
  render(<DocumentSelectionPanel slug="asset-management" currentDocuments={[document]} workspaceIds={[workspaceId]} folderIds={[]} foldersByWorkspace={{}} onApply={vi.fn()} onClose={vi.fn()} returnFocus={opener} />);

  const dialog = await screen.findByRole("dialog", { name: "파일 선택" });
  const closeButton = within(dialog).getByRole("button", { name: "닫기" });
  const lastControl = await screen.findByRole("checkbox", { name: "운용 규정.md 선택" });
  expect(closeButton).toHaveFocus();

  await user.tab({ shift: true });
  expect(lastControl).toHaveFocus();
  await user.tab();
  expect(closeButton).toHaveFocus();
  opener.remove();
});

it("browses only existing domain documents, permits explicit last deselection, and restores focus on Escape", async () => {
  stubRootLibrary();
  const close = vi.fn();
  const apply = vi.fn();
  const opener = documentNode("button");
  opener.focus();
  const user = userEvent.setup();
  render(<DocumentSelectionPanel slug="asset-management" currentDocuments={[document]} workspaceIds={[workspaceId]} folderIds={[]} foldersByWorkspace={{}} onApply={apply} onClose={close} returnFocus={opener} />);

  const dialog = await screen.findByRole("dialog", { name: "파일 선택" });
  expect(dialog).toBeVisible();
  expect(screen.queryByText("새 문서 파일")).not.toBeInTheDocument();
  await user.click(screen.getByRole("checkbox", { name: "운용 규정.md 선택" }));
  await user.click(screen.getByRole("button", { name: "선택 적용" }));
  expect(apply).toHaveBeenCalledWith([]);

  await user.keyboard("{Escape}");
  expect(close).toHaveBeenCalled();
  expect(opener).toHaveFocus();
  opener.remove();
});

it("keeps embedded folder, workspace, and viewer navigation out of chat history", async () => {
  const personalId = "22222222-2222-4222-8222-222222222222";
  const folder = { id: "folder-1", metadata_revision: 1, name: "리스크", parent_id: null, has_children: false };
  const folderDocument = { ...document, folder_id: folder.id };
  const root = { ancestors: [], documents: [document], folder: null, folders: [folder], next_document_cursor: null, next_folder_cursor: null, workspace: { id: workspaceId, name: "회사 규정", kind: "company", expires_at: null } } as const;
  vi.stubGlobal("fetch", vi.fn(async (input) => {
    const path = String(input);
    if (path.endsWith("/library")) return Response.json({ domain_id: "domain-1", display_name: "자산운용", connection_version_id: "connection-1", selection_limit: 2, workspace_options: [root.workspace, { id: personalId, name: "개인 연구", kind: "personal", expires_at: null }] });
    if (path.includes(`workspaces/${workspaceId}`) && path.includes("folder_id=folder-1")) return Response.json({ ...root, folder, folders: [], documents: [folderDocument] });
    if (path.endsWith(`workspaces/${workspaceId}`)) return Response.json(root);
    if (path.endsWith(`workspaces/${personalId}`)) return Response.json({ ...root, workspace: { id: personalId, name: "개인 연구", kind: "personal", expires_at: null }, documents: [], folders: [] });
    if (path.endsWith(`/documents/${documentId}/versions`)) return Response.json({ items: [{ id: "version-1", number: 1, media_type: "text/markdown", size: 10, status: "ready" }], next_cursor: null });
    if (path.endsWith("/versions/version-1/preview")) return Response.json({ asset_version_id: "version-1", document_id: documentId, kind: "text", name: document.name, page_count: null, size: 10, text: "원문", version: 1 });
    throw new Error(`Unexpected path: ${path}`);
  }));
  window.history.replaceState(null, "", `/workshop/rag/domains/asset-management/chat?selected=${workspaceId}:${documentId}`);
  const chatUrl = window.location.href;
  const user = userEvent.setup();
  const close = vi.fn();
  render(<DocumentSelectionPanel
    slug="asset-management"
    currentDocuments={[document]}
    workspaceIds={[workspaceId, personalId]}
    folderIds={[]}
    foldersByWorkspace={{}}
    onApply={vi.fn()}
    onClose={close}
    returnFocus={null}
  />);

  const documentOpener = await screen.findByRole("button", { name: `${document.name} 열기` });
  await user.click(documentOpener);
  expect(await screen.findByText("원문")).toBeVisible();
  expect(window.location.href).toBe(chatUrl);
  expect(screen.getByRole("button", { name: "문서 닫기" })).toHaveFocus();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  expect(screen.getByRole("dialog", { name: "파일 선택" })).toBeVisible();
  expect(close).not.toHaveBeenCalled();
  expect(documentOpener).toHaveFocus();
  await user.click(screen.getByRole("button", { name: "리스크 폴더 열기" }));
  expect(await screen.findByRole("button", { name: `${folderDocument.name} 열기` })).toBeVisible();
  expect(window.location.href).toBe(chatUrl);
  await user.click(screen.getByRole("button", { name: "개인 연구" }));
  expect(await screen.findByRole("heading", { name: "개인 연구" })).toBeVisible();
  expect(window.location.href).toBe(chatUrl);
});

function documentNode(tag: "button"): HTMLButtonElement {
  const node = window.document.createElement(tag);
  window.document.body.append(node);
  return node;
}

function stubRootLibrary() {
  vi.stubGlobal("fetch", vi.fn(async (input) => {
    const path = String(input);
    if (path.endsWith("/library")) return Response.json({ domain_id: "domain-1", display_name: "자산운용", connection_version_id: "connection-1", selection_limit: 2, workspace_options: [{ id: workspaceId, name: "회사 규정", kind: "company", expires_at: null }] });
    if (path.endsWith(`/workspaces/${workspaceId}`)) return Response.json({ ancestors: [], documents: [document], folder: null, folders: [], next_document_cursor: null, next_folder_cursor: null, workspace: { id: workspaceId, name: "회사 규정", kind: "company", expires_at: null } });
    throw new Error(`Unexpected path: ${path}`);
  }));
}
