import { vi } from "vitest";
import * as api from "./api";
import { documentMoveSource, folderMoveSource, moveDestinationProblem } from "./movement";

afterEach(() => vi.unstubAllGlobals());

it.each(["moveDocument", "moveFolder"] as const)("%s sends the exact revision and encoded route once", async (name) => {
  const fetcher = vi.fn(async () => Response.json({ id: "source", changed: true, metadata_revision: 4 }));
  vi.stubGlobal("fetch", fetcher);
  expect(api).toHaveProperty(name, expect.any(Function));
  const move = (api as unknown as Record<string, (workspace: string, id: string, body: unknown) => Promise<unknown>>)[name];
  await move("space/x", "source/y", { destination_folder_id: "folder-b", expected_revision: 3 });
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[0]).toEqual([`/api/v1/workspaces/space%2Fx/${name === "moveDocument" ? "documents" : "folders"}/source%2Fy/move`, expect.objectContaining({ method: "POST", body: '{"destination_folder_id":"folder-b","expected_revision":3}' })]);
});

it("refuses missing revision and self or authoritative descendant destinations", () => {
  expect(folderMoveSource({ id: "a", name: "A", parent_id: null, metadata_revision: 0 }, "company")).toBeNull();
  expect(documentMoveSource({ id: "doc", workspace_id: "company", metadata_revision: undefined } as unknown as api.DocumentSummary)).toBeNull();
  const source = { kind: "folder" as const, id: "a", name: "A", workspaceId: "company", parentId: null, revision: 1 };
  const a = { id: "a", name: "A", parent_id: null, metadata_revision: 1 };
  const root: api.LibraryPage = { workspace: { id: "company", name: "Company", kind: "company", expires_at: null }, folder: null, ancestors: [], folders: [], documents: [], next_document_cursor: null, next_folder_cursor: null };
  expect(moveDestinationProblem(source, null)).toBeTruthy();
  expect(moveDestinationProblem(source, root)).toBe("이미 이 위치에 있습니다.");
  expect(moveDestinationProblem(source, { ...root, folder: a })).toMatch(/자기 자신/);
  expect(moveDestinationProblem(source, { ...root, folder: { ...a, id: "child", parent_id: "a" }, ancestors: [a] })).toMatch(/하위 폴더/);
  expect(moveDestinationProblem(source, { ...root, folder: { ...a, id: "b" } })).toBeNull();
});
