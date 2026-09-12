import Link from "next/link";

import { ConversationPage } from "../../../../../../../features/rag/conversation/ConversationPage";
import { selectionFromDocuments } from "../../../../../../../features/rag/conversation/types";
import type { Domain } from "../../../../../../../features/rag/domains/api";
import type { DomainLibraryContext } from "../../../../../../../features/rag/domains/library-api";
import type { DocumentSummary } from "../../../../../../../features/assets/api";
import { ApiError } from "../../../../../../../shared/api/client";
import { serverApiRequest } from "../../../../../../../shared/api/server-client";
import { incomingCookieHeader, requireWorkspaceUser } from "../../../../../../../shared/auth/server-session";
import { ragDomainChatPath, routes } from "../../../../../../../shared/routing/routes";
import { captureServerRoute, ServerRouteFailure } from "../../../../../../../shared/ui/ServerRouteFailure";

interface RagDomainChatRouteProps {
  params: Promise<{ slug: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function RagDomainChatRoute({ params, searchParams }: RagDomainChatRouteProps) {
  const [{ slug }, query] = await Promise.all([params, searchParams]);
  const result = await captureServerRoute(async () => {
    await requireWorkspaceUser(ragDomainChatPath(slug));
    const cookie = await incomingCookieHeader();
    const domain = await serverApiRequest<Domain>(
      `/api/v1/rag/domains/${encodeURIComponent(slug)}`,
      {},
      cookie,
    );
    const rawSelection = selectedValues(query.selected);
    if (rawSelection === null) return { domain, selection: null };
    const pairs = parseSelectedPairs(rawSelection);
    const base = `/api/v1/rag/domains/${encodeURIComponent(slug)}/library`;
    const context = await serverApiRequest<DomainLibraryContext>(base, {}, cookie);
    if (!domain.connection_version || context.connection_version_id !== domain.connection_version.id
      || pairs.length > context.selection_limit
      || pairs.some((pair) => !context.workspace_options.some((workspace) => workspace.id === pair.workspaceId))) throw invalidSelection();
    const documents = await Promise.all(pairs.map(({ workspaceId, documentId }) => serverApiRequest<DocumentSummary>(`${base}/workspaces/${workspaceId}/documents/${documentId}`, {}, cookie)));
    if (documents.some((document, index) => document.id !== pairs[index].documentId || document.workspace_id !== pairs[index].workspaceId)) throw invalidSelection();
    return { domain, selection: selectionFromDocuments(documents) };
  });
  if (!result.ok && result.failure.status === 404 && result.failure.code === "not_found") {
    return (
      <main className="route-error" role="alert">
        <p className="eyebrow">도메인 대화</p>
        <h1>도메인을 찾을 수 없습니다</h1>
        <p>주소가 올바른지 확인하거나 사용 가능한 도메인을 다시 선택해 주세요.</p>
        <Link href={routes.workshopRagSearch}>도메인 선택으로 돌아가기</Link>
      </main>
    );
  }
  if (!result.ok) return <ServerRouteFailure failure={result.failure} />;
  return <ConversationPage domain={result.value.domain} initialSelection={result.value.selection} />;
}

const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function selectedValues(value: string | string[] | undefined): string[] | null {
  if (value === undefined) return null;
  return Array.isArray(value) ? value : [value];
}

function parseSelectedPairs(values: string[]): { workspaceId: string; documentId: string }[] {
  if (values.length === 0) throw invalidSelection();
  const pairs = values.map((value) => {
    const [workspaceId, documentId, extra] = value.split(":");
    if (extra !== undefined || !uuidPattern.test(workspaceId ?? "") || !uuidPattern.test(documentId ?? "")) throw invalidSelection();
    return { workspaceId, documentId };
  });
  if (new Set(pairs.map(({ documentId }) => documentId)).size !== pairs.length) throw invalidSelection();
  return pairs;
}

function invalidSelection(): ApiError {
  return new ApiError("Invalid selected documents", 422, "invalid_document_selection");
}
