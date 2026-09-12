import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";
import { EvaluationSourceSelector } from "./EvaluationSourceSelector";
import type { SavedConfiguration } from "./api";

const configuration: SavedConfiguration = {
  id: "config", version_id: "version", owner_id: "owner", name: "Synthetic configuration", version: 1,
  document_processing_profile_id: "processing", indexing_profile_id: "indexing", retrieval_profile_id: "retrieval", generation_profile_id: null,
  answer_policy: { id: "answer", version: 1, mode: "extractive", min_semantic_score: 0.7, min_keyword_coverage: 0.5, require_complete_provenance: true, conflict_mode: "separate_sources" },
  workspace_ids: ["workspace"], evaluation_state: "pending", is_system: false, is_default: false, experimental: true, search_ready: true, answer_ready: false, service_ready: false,
  search_reasons: [], answer_reasons: [], generation_execution_preview: null,
};
afterEach(() => vi.unstubAllGlobals());

it("lists metadata before reading a selected READY source and ignores a late preview after scope change", async () => {
  let finish!: (value: Response) => void;
  let signal: AbortSignal | undefined;
  const fetcher = vi.fn<typeof fetch>(async (url, init) => {
    if (String(url).endsWith("/documents")) return Response.json({ documents: [
      { document_id: "doc", workspace_id: "workspace", asset_version_id: "small", title: "Small ready", number: 1, ready: true },
      { document_id: "other", workspace_id: "workspace", asset_version_id: "unready", title: "Not indexed", number: 2, ready: false },
    ], next_cursor: null });
    signal = init?.signal ?? undefined; return new Promise((resolve) => { finish = resolve; });
  });
  vi.stubGlobal("fetch", fetcher);
  const preview = vi.fn(); const user = userEvent.setup();
  render(<EvaluationSourceSelector configurations={[configuration]} workspaces={[{ id: "workspace", name: "Workspace", kind: "company", expires_at: null }]} disabled={false} onPreview={preview} />);
  await user.click(screen.getByRole("checkbox", { name: "Workspace" }));
  expect(fetcher).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "문서 목록 불러오기" }));
  expect(await screen.findByRole("checkbox", { name: "Not indexed v2 (준비되지 않음)" })).toBeDisabled();
  await user.click(screen.getByRole("checkbox", { name: "Small ready v1" }));
  expect(fetcher).toHaveBeenCalledTimes(1);
  await user.click(screen.getByRole("button", { name: "근거 불러오기" }));
  expect(JSON.parse(fetcher.mock.calls[1][1]!.body as string)).toEqual({ configuration_version_id: "version", workspace_ids: ["workspace"], asset_version_ids: ["small"] });
  await user.click(screen.getByRole("checkbox", { name: "Workspace" }));
  expect(signal?.aborted).toBe(true);
  await act(async () => finish(Response.json({ complete: true, documents: [], evidence: [], document_count: 0, evidence_count: 0 })));
  expect(preview.mock.calls.every(([value]) => value === null)).toBe(true);
  expect(screen.queryByRole("checkbox", { name: "Small ready v1" })).not.toBeInTheDocument();
});

it("rejects an incomplete preview without treating truncated evidence as authoritative", async () => {
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (url) => String(url).endsWith("/documents")
    ? Response.json({ documents: [{ document_id: "doc", workspace_id: "workspace", asset_version_id: "small", title: "Small ready", number: 1, ready: true }], next_cursor: null })
    : Response.json({ complete: true, documents: [], evidence: [], document_count: 1, evidence_count: 1 })));
  const preview = vi.fn(); const user = userEvent.setup();
  render(<EvaluationSourceSelector configurations={[configuration]} workspaces={[{ id: "workspace", name: "Workspace", kind: "company", expires_at: null }]} disabled={false} onPreview={preview} />);
  await user.click(screen.getByRole("checkbox", { name: "Workspace" }));
  await user.click(screen.getByRole("button", { name: "문서 목록 불러오기" }));
  await user.click(await screen.findByRole("checkbox", { name: "Small ready v1" }));
  await user.click(screen.getByRole("button", { name: "근거 불러오기" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("부분 근거는 사용하지 않습니다");
  expect(preview.mock.calls.every(([value]) => value === null)).toBe(true);
});
