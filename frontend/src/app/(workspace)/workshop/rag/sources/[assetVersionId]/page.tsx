import { SourceViewer } from "../../../../../../features/rag/search/SourceViewer";
import {
  parseSourceQuery,
  type SourceSearchParams,
} from "../../../../../../features/rag/search/source-route-query";

interface SourceRouteProps {
  params: Promise<{ assetVersionId: string }>;
  searchParams: Promise<SourceSearchParams>;
}

export default async function RagSourceRoute({ params, searchParams }: SourceRouteProps) {
  const [{ assetVersionId }, query] = await Promise.all([params, searchParams]);
  const { projectionId, page, highlights } = parseSourceQuery(query);
  if (!assetVersionId || !projectionId) {
    return (
      <main className="source-viewer-shell">
        <p role="alert">원문 요청 정보가 올바르지 않습니다.</p>
      </main>
    );
  }
  return (
    <SourceViewer
      assetVersionId={assetVersionId}
      projectionId={projectionId}
      highlights={highlights}
      page={page}
    />
  );
}
