import { LabWorldPage } from "../../../features/public-labs/LabWorldPage";
import { loadPublicLabCatalog } from "../../../features/public-labs/catalog";

export const metadata = {
  alternates: { canonical: "/" },
};

export default function LabsRoute() {
  return <LabWorldPage catalog={loadPublicLabCatalog()} />;
}
