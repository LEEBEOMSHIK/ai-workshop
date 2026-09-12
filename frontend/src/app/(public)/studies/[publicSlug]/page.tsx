import { ApiError } from "../../../../shared/api/client";
import { getPublicStudy } from "../../../../features/publishing/api";
import { normalizeCatalogQuery, type CatalogSearchParams } from "../../../../features/publishing/catalog-query";
import {
  PublicStudyDetail,
  PublicStudyNotFound,
  PublicStudyUnavailable,
} from "../../../../features/publishing/PublicStudies";

export const dynamic = "force-dynamic";

export default async function PublicStudyRoute({
  params,
  searchParams,
}: {
  params: Promise<{ publicSlug: string }>;
  searchParams?: Promise<CatalogSearchParams>;
}) {
  const { publicSlug } = await params;
  const search = await searchParams;
  const query = search && (search.page !== undefined || search.topic !== undefined) ? normalizeCatalogQuery(search) : undefined;
  const result = await loadStudy(publicSlug);
  if (result.status === "ready") return <PublicStudyDetail snapshot={result.snapshot} query={query} />;
  if (result.status === "not-found") return <PublicStudyNotFound />;
  return <PublicStudyUnavailable />;
}

async function loadStudy(publicSlug: string) {
  try {
    return { status: "ready" as const, snapshot: await getPublicStudy(publicSlug) };
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 404) return { status: "not-found" as const };
    return { status: "unavailable" as const };
  }
}
