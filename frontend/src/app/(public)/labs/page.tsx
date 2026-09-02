import { LabWorldPage } from "../../../features/public-labs/LabWorldPage";
import { listPublicLabs } from "../../../features/public-labs/catalog";

export default function LabsRoute() {
  return <LabWorldPage labs={listPublicLabs()} />;
}
