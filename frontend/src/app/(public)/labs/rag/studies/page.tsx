import { listPublicStudyCatalog } from "../../../../../features/publishing/api";
import { normalizeCatalogQuery, type CatalogQuery, type CatalogSearchParams } from "../../../../../features/publishing/catalog-query";
import { PublicStudyList } from "../../../../../features/publishing/PublicStudies";

export const dynamic = "force-dynamic";

export default async function PublicStudiesRoute({ searchParams }: { searchParams?: Promise<CatalogSearchParams> } = {}) {
  const query = normalizeCatalogQuery(await searchParams);
  const result = await loadStudyList(query);
  return <PublicStudyList result={result} query={query} />;
}

async function loadStudyList(query: CatalogQuery) {
  try {
    const { items, ...catalog } = await listPublicStudyCatalog(query);
    return { status: "ready" as const, items, catalog };
  } catch {
    return { status: "unavailable" as const };
  }
}
