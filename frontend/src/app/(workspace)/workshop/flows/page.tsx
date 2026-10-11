import { FlowchartsPage } from "../../../../features/flowcharts/FlowchartsPage";
import { findFlow } from "../../../../features/flowcharts/catalog";
import { requireWorkspaceUser } from "../../../../shared/auth/server-session";
import { flowchartPath, routes } from "../../../../shared/routing/routes";
import { flowCatalogForUser } from "./catalog";

export default async function FlowsRoute() {
  const user = await requireWorkspaceUser(routes.workshopFlows);
  const flows = flowCatalogForUser(user);
  const selectedFlow = findFlow(flows, "rag", "answer")!;
  return <FlowchartsPage flows={flows} selectedFlow={selectedFlow} flowHref={flowchartPath} />;
}
