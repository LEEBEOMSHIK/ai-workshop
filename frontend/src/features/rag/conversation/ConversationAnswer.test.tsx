import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { ConversationAnswer } from "./ConversationAnswer";
import type { DomainSearchResult } from "./api";
import type { CompletedTurn } from "./types";

it("labels the server-confirmed selected scope with document names and opens its exact used version", async () => {
  const document = { active_version_id: "asset-version-new", folder_id: null, id: "document-1", job_id: null, latest_version: 9, latest_version_id: "asset-version-new", name: "운용 규정.md", status: "ready", workspace_id: "workspace-1" } as const;
  const turn = {
    type: "answer",
    query: "질문",
    result: result({ identities: [{ document_id: document.id, asset_version_id: "asset-version-used", projection_id: "projection-1", index_build_id: "build-1" }], fingerprint: "not-a-label" }),
    scope: { workspaceIds: ["workspace-1"], workspaceNames: ["회사 규정"], folderIds: [], folderNames: [], documentIds: [document.id], documentNames: [document.name], documents: [document] },
  } satisfies CompletedTurn;
  const openVersion = vi.fn();
  const user = userEvent.setup();
  render(<ConversationAnswer turn={turn} onOpenEvidence={vi.fn()} onOpenSelectedVersion={openVersion} />);

  expect(screen.getByText("실제 사용 문서: 운용 규정.md")).toBeVisible();
  expect(screen.queryByText("not-a-label")).not.toBeInTheDocument();
  expect(screen.queryByText("asset-version-used")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "운용 규정.md 사용 버전 원문 열기" }));
  expect(openVersion).toHaveBeenCalledWith(document, "asset-version-used");
});

function result(selectedScope: NonNullable<DomainSearchResult["selected_scope"]> | null): CompletedTurn["result"] {
  return {
    status: "insufficient_evidence", answer: null, conflict_state: "none", conflicts: [], warnings: [], related_sources: [],
    configuration_version: { configuration_id: "configuration-1", version_id: "version-1", version: 1 }, experimental: false, resolved_query: "질문",
    generation: { status: "insufficient_evidence", text: null, citations: [], reason_codes: [], turn_id: "turn-1", validation_token: "signed", execution: null },
    domain_context: { domain_id: "domain-1", connection_version_id: "connection-1", workspace_ids: ["workspace-1"], folder_ids: [] },
    selected_scope: selectedScope,
  };
}
