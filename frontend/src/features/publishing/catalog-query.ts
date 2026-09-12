import { publicStudyPath, routes } from "../../shared/routing/routes";

export type CatalogSearchParams = Record<string, string | string[] | undefined>;
export type CatalogQuery = { page: number; topic?: string };

export function normalizeCatalogQuery(params: CatalogSearchParams = {}): CatalogQuery {
  const page = typeof params.page === "string" && /^[0-9]+$/.test(params.page) ? Number(params.page) : 1;
  const topic = typeof params.topic === "string" && params.topic.length <= 128 && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(params.topic) ? params.topic : undefined;
  return { page: Number.isSafeInteger(page) && page > 0 && page <= 1_000_000 ? page : 1, ...(topic ? { topic } : {}) };
}

function querySuffix(query?: CatalogQuery): string {
  if (!query) return "";
  const valid = normalizeCatalogQuery({ page: String(query.page), topic: query.topic });
  const params = new URLSearchParams();
  if (valid.topic) params.set("topic", valid.topic);
  params.set("page", String(valid.page));
  return `?${params}`;
}

export function catalogPath(query?: CatalogQuery): string {
  return `${routes.ragStudies}${querySuffix(query)}`;
}

export function studyCatalogPath(slug: string, query?: CatalogQuery): string {
  return `${publicStudyPath(slug)}${querySuffix(query)}`;
}

export function catalogPages(page: number, totalPages: number): (number | "gap-before" | "gap-after")[] {
  if (totalPages <= 0) return [];
  const start = Math.max(2, page - 2);
  const end = Math.min(totalPages - 1, page + 2);
  const pages: (number | "gap-before" | "gap-after")[] = [1];
  if (start > 2) pages.push("gap-before");
  for (let value = start; value <= end; value++) pages.push(value);
  if (end < totalPages - 1) pages.push("gap-after");
  if (totalPages > 1) pages.push(totalPages);
  return pages;
}
