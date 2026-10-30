import { apiRequest } from "../../../shared/api/client";
import type { components } from "../../../shared/api/schema";

export type SetupOptions = components["schemas"]["DeploymentSetupOptionsResponse"];

export function loadSetupOptions(signal?: AbortSignal): Promise<SetupOptions> {
  return apiRequest("/api/v1/admin/rag/deployment-setup-options", { signal });
}
