import { ExecutionDetailPage } from "../../../../../../../features/rag/executions/ExecutionDetailPage";
import { requireOwner } from "../../../../../../../shared/auth/server-session";
import { executionPath } from "../../../../../../../shared/routing/routes";
export default async function Page({ params }: { params: Promise<{ turnId: string }> }) {
  const { turnId } = await params;
  await requireOwner(executionPath(turnId, "legacy"));
  return <ExecutionDetailPage id={turnId} kind="legacy" />;
}
