import type { SearchResult, SearchSubmissionContext } from "./api";

const workspaceKindLabels: Record<
  SearchSubmissionContext["workspaces"][number]["kind"],
  string
> = {
  company: "전사",
  team: "팀",
  personal: "개인",
  temporary: "임시",
};

export function ConfigurationProvenance({
  result,
  context,
}: {
  result: SearchResult;
  context: SearchSubmissionContext;
}) {
  return (
    <div className="configuration-provenance" aria-label="사용한 저장 RAG 구성">
      <strong>선택한 구성 {context.configuration.name}</strong>
      <span>선택 구성 ID {context.configuration.id}</span>
      <span>선택 버전 ID {context.configuration.versionId}</span>
      <span>선택 버전 {context.configuration.version}</span>
      <span>{context.configuration.experimental ? "선택 구성 실험" : "선택 구성 일반"}</span>
      <span>응답 구성 ID {result.configuration_version.configuration_id}</span>
      <span>응답 버전 ID {result.configuration_version.version_id}</span>
      <span>응답 버전 {result.configuration_version.version}</span>
      <span>{result.experimental ? "실험 실행" : "일반 실행"}</span>
      <span>{context.experimentalConsent ? "실험 사용 동의" : "실험 사용 미동의"}</span>
    </div>
  );
}

export function SourceScopeProvenance({
  workspaceId,
  folderId,
  context,
}: {
  workspaceId: string;
  folderId: string | null;
  context: SearchSubmissionContext;
}) {
  const workspace = context.workspaces.find((candidate) => candidate.id === workspaceId);
  const folder = context.folders.find(
    (candidate) => candidate.id === folderId && candidate.workspaceId === workspaceId,
  );

  return (
    <div className="source-scope">
      <p className="source-workspace">
        {workspace ? (
          <>
            <span className={`workspace-badge ${workspace.kind}`}>
              {workspaceKindLabels[workspace.kind]}
            </span>{" "}
            {workspace.name} · {workspace.id}
          </>
        ) : (
          workspaceId
        )}
      </p>
      {folderId ? <p>폴더 {folder ? `${folder.name} · ${folder.id}` : folderId}</p> : null}
    </div>
  );
}
