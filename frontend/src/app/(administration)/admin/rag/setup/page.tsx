import { ModelSetupPage } from "../../../../../features/rag/setup/ModelSetupPage";
import { routes } from "../../../../../shared/routing/routes";
import { requireOwner } from "../../../../../shared/auth/server-session";

export default async function ModelSetupRoute() {
  await requireOwner(routes.adminRagSetup);
  return <ModelSetupPage />;
}
