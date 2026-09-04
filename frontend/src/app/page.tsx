import { LabEntrancePage } from "../features/public-labs/LabEntrancePage";
import { loadPublicLabCatalog } from "../features/public-labs/catalog";

export const metadata = {
  alternates: { canonical: "/" },
};

export default function HomeRoute() {
  return <LabEntrancePage catalog={loadPublicLabCatalog()} />;
}
