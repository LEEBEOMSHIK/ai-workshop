import { LabWorldPage } from "../../../features/public-labs/LabWorldPage";
import { loadPublicLabCatalog } from "../../../features/public-labs/catalog";
import { routes } from "../../../shared/routing/routes";

export const metadata = {
  alternates: { canonical: routes.labs },
};

export default function LabsRoute() {
  return <LabWorldPage catalog={loadPublicLabCatalog()} />;
}
