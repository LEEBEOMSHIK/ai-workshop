import { ComparisonDetailPage } from "../../../../../../features/rag/comparisons/ComparisonDetailPage";
import { requireOwner } from "../../../../../../shared/auth/server-session";
import { comparisonPath } from "../../../../../../shared/routing/routes";

export default async function Page({ params }: { params: Promise<{ comparisonId: string }> }) {
  const { comparisonId } = await params;
  await requireOwner(comparisonPath(comparisonId));
  return <ComparisonDetailPage id={comparisonId} />;
}
