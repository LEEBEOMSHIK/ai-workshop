import { notFound } from "next/navigation";
import { FlowchartsPage } from "../../../../../../features/flowcharts/FlowchartsPage";
import { findFlow } from "../../../../../../features/flowcharts/catalog";
import { requireWorkspaceUser } from "../../../../../../shared/auth/server-session";
import { flowchartPath } from "../../../../../../shared/routing/routes";
import { flowCatalogForUser } from "../../catalog";

export default async function FlowRoute({ params }: { params: Promise<{ category: string; flow: string }> }) {
  const { category, flow } = await params;
  const user = await requireWorkspaceUser(flowchartPath(category, flow));
  const flows = flowCatalogForUser(user);
  const selectedFlow = findFlow(flows, category, flow);
  if (!selectedFlow) notFound();
  return <FlowchartsPage flows={flows} selectedFlow={selectedFlow} flowHref={flowchartPath} />;
}
