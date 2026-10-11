import type { SessionUser } from "../../../../features/identity/session";
import type { FlowDefinition } from "../../../../features/flowcharts/types";
import { validateFlowCatalog } from "../../../../features/flowcharts/catalog";
import { ragFlows } from "../../../../features/rag/flows/catalog";
import { projectAgentFlows } from "../../../../features/project-agents/flows";
import { canAccessAdmin } from "../../../../shared/auth/access";

const flows: readonly FlowDefinition[] = [...ragFlows, ...projectAgentFlows];
validateFlowCatalog(flows);

export function flowCatalogForUser(user: SessionUser): readonly FlowDefinition[] {
  return flows.map(flow => ({ ...flow, links: flow.links.filter(link => link.audience === "workspace" || canAccessAdmin(user)) }));
}
