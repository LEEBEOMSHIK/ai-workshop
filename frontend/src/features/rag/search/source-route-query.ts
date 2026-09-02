import type { HighlightSpan } from "./api";

type SearchParamValue = string | string[] | undefined;
export type SourceSearchParams = Record<string, SearchParamValue>;

interface EncodedHighlight {
  evidenceUnitId: string;
  charStart: number;
  charEnd: number;
  page: number | null;
  bbox: [number, number, number, number] | null;
  score: number | null;
}

const MAX_HIGHLIGHTS = 20;

export function buildSourceHref(
  assetVersionId: string,
  projectionId: string,
  highlights: HighlightSpan[] = [],
  page?: number | null,
): string {
  const query = new URLSearchParams({ projectionId });
  if (isPositiveInteger(page)) query.set("page", String(page));
  for (const highlight of highlights.slice(0, MAX_HIGHLIGHTS)) {
    const encoded: EncodedHighlight = {
      evidenceUnitId: highlight.evidence_unit_id,
      charStart: highlight.char_start,
      charEnd: highlight.char_end,
      page: highlight.page,
      bbox: highlight.bbox,
      score: highlight.score,
    };
    query.append(highlight.kind, JSON.stringify(encoded));
  }
  return `/app/rag/sources/${encodeURIComponent(assetVersionId)}?${query}`;
}

export function parseSourceQuery(searchParams: SourceSearchParams): {
  projectionId: string;
  page: number | null;
  highlights: HighlightSpan[];
} {
  const projectionId = singleValue(searchParams.projectionId) ?? "";
  const requestedPage = Number(singleValue(searchParams.page));
  const page = isPositiveInteger(requestedPage) ? requestedPage : null;
  const values: Array<{ kind: HighlightSpan["kind"]; value: string }> = [
    ...allValues(searchParams.keyword).map((value) => ({ kind: "keyword" as const, value })),
    ...allValues(searchParams.semantic).map((value) => ({ kind: "semantic" as const, value })),
  ];
  const highlights = values.slice(0, MAX_HIGHLIGHTS).flatMap(({ kind, value }) => {
    const parsed = parseHighlight(kind, value);
    return parsed ? [parsed] : [];
  });
  return { projectionId, page, highlights };
}

function parseHighlight(kind: HighlightSpan["kind"], value: string): HighlightSpan | null {
  let candidate: unknown;
  try {
    candidate = JSON.parse(value) as unknown;
  } catch {
    return null;
  }
  if (!isRecord(candidate)) return null;
  const evidenceUnitId = candidate.evidenceUnitId;
  const charStart = candidate.charStart;
  const charEnd = candidate.charEnd;
  const page = candidate.page;
  const bbox = candidate.bbox;
  const score = candidate.score;
  if (
    typeof evidenceUnitId !== "string" ||
    evidenceUnitId.length === 0 ||
    !Number.isInteger(charStart) ||
    !Number.isInteger(charEnd) ||
    (charStart as number) < 0 ||
    (charEnd as number) <= (charStart as number) ||
    !(page === null || isPositiveInteger(page)) ||
    !(bbox === null || isBoundingBox(bbox)) ||
    !(score === null || (typeof score === "number" && Number.isFinite(score)))
  ) {
    return null;
  }
  return {
    kind,
    evidence_unit_id: evidenceUnitId,
    text: "",
    char_start: charStart as number,
    char_end: charEnd as number,
    page: page as number | null,
    bbox: bbox as [number, number, number, number] | null,
    score: score as number | null,
    warnings: [],
  };
}

function singleValue(value: SearchParamValue): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function allValues(value: SearchParamValue): string[] {
  if (value === undefined) return [];
  return Array.isArray(value) ? value : [value];
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

function isBoundingBox(value: unknown): value is [number, number, number, number] {
  return Array.isArray(value) && value.length === 4 && value.every(
    (coordinate) => typeof coordinate === "number" && Number.isFinite(coordinate),
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
