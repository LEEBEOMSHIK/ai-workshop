import { Link } from "react-router-dom";

import type { RelatedSourceData } from "./api";

interface RelatedSourcesProps {
  sources: RelatedSourceData[];
  workspaceNames: ReadonlyMap<string, string>;
}

export function RelatedSources({ sources, workspaceNames }: RelatedSourcesProps) {
  return (
    <section className="related-sources" aria-labelledby="related-sources-title">
      <h2 id="related-sources-title">관련 문서</h2>
      {sources.length === 0 ? <p>관련 문서가 없습니다.</p> : null}
      <div className="source-card-list">
        {sources.map((source) => (
          <article className="source-card" key={source.chunk_id}>
            {workspaceNames.has(source.workspace_id) ? (
              <p className="source-workspace">{workspaceNames.get(source.workspace_id)}</p>
            ) : null}
            <h3>{source.title}</h3>
            <p>버전 {source.asset_version_number}</p>
            {source.section_path.length > 0 ? (
              <p>위치: {source.section_path.join(" › ")}</p>
            ) : null}
            <Link
              to={`/rag/sources/${source.asset_version_id}?projectionId=${encodeURIComponent(source.projection_id)}`}
            >
              원문 열기
            </Link>
          </article>
        ))}
      </div>
    </section>
  );
}
