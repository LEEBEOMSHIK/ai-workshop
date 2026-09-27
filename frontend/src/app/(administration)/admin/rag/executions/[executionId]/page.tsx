import { ExecutionDetailPage } from "../../../../../../features/rag/executions/ExecutionDetailPage";
import { requireOwner } from "../../../../../../shared/auth/server-session";
import { executionPath } from "../../../../../../shared/routing/routes";
export default async function Page({ params }: { params: Promise<{ executionId: string }> }) {
  const { executionId } = await params;
  await requireOwner(executionPath(executionId, "execution"));
  return <ExecutionDetailPage id={executionId} kind="execution" />;
}
