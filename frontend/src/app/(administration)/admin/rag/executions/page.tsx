import { ExecutionListPage } from "../../../../../features/rag/executions/ExecutionListPage";
import { requireOwner } from "../../../../../shared/auth/server-session";
import { routes } from "../../../../../shared/routing/routes";
import type { ExecutionSearchRequest } from "../../../../../features/rag/executions/api";
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const params = await searchParams;
  const initialFilters: ExecutionSearchRequest = {};
  for (const key of ["domain_id", "configuration_version_id", "started_after", "started_before", "answer_status"] as const) {
    if (typeof params[key] === "string") initialFilters[key] = params[key];
  }
  if (["running", "completed", "failed", "cancelled", "interrupted"].includes(String(params.status))) initialFilters.status = params.status as ExecutionSearchRequest["status"];
  if (params.kind === "conversation" || params.kind === "evaluation") initialFilters.kind = params.kind;
  if (["request", "history", "contextualization", "retrieval", "selection", "generation", "citation_validation", "persistence"].includes(String(params.failed_stage))) initialFilters.failed_stage = params.failed_stage as ExecutionSearchRequest["failed_stage"];
  await requireOwner(routes.adminRagExecutions);
  return <ExecutionListPage initialFilters={initialFilters} />;
}
