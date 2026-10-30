import { ComparisonListPage } from "../../../../../features/rag/comparisons/ComparisonListPage";
import { requireOwner } from "../../../../../shared/auth/server-session";
import { routes } from "../../../../../shared/routing/routes";

export default async function Page() {
  await requireOwner(routes.adminRagComparisons);
  return <ComparisonListPage />;
}
