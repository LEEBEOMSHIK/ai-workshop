import { RagLabOverviewPage } from "../../../../features/public-labs/RagLabOverviewPage";
import { listPublicStudies } from "../../../../features/publishing/api";

export const dynamic = "force-dynamic";

export default async function RagLabRoute() {
  const studies = await loadStudies();
  return <RagLabOverviewPage studies={studies} />;
}

async function loadStudies() {
  try {
    const response = await listPublicStudies();
    return response.items;
  } catch {
    return [];
  }
}
