import { useEffect, useRef, useState } from "react";
import { listEvaluationDocuments, previewEvaluationSources, type AuthoringDocumentsResponse, type AuthoringPreview, type SavedConfiguration, type Workspace } from "./api";

export function EvaluationSourceSelector({ configurations, workspaces, disabled, onPreview, onLoading, beginOperation, isCurrentOperation }: {
  configurations: SavedConfiguration[]; workspaces: Workspace[]; disabled: boolean;
  onPreview: (preview: AuthoringPreview | null) => void;
  onLoading?: (loading: boolean) => void;
  beginOperation?: () => number; isCurrentOperation?: (intent: number) => boolean;
}) {
  const candidates = configurations.filter((item) => !item.is_system);
  const [versionId, setVersionId] = useState(candidates[0]?.version_id ?? "");
  const [workspaceIds, setWorkspaceIds] = useState<string[]>([]);
  const [assets, setAssets] = useState<string[]>([]);
  const [listing, setListing] = useState<AuthoringDocumentsResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const operation = useRef<AbortController | null>(null);
  useEffect(() => () => operation.current?.abort(), []);
  function invalidate(clearDocuments: boolean) {
    operation.current?.abort(); operation.current = null; setBusy(false); onLoading?.(false); setError(""); onPreview(null);
    if (clearDocuments) { setListing(null); setAssets([]); }
  }
  async function load(preview: boolean, cursor?: string) {
    if (disabled || busy || operation.current || !versionId || !workspaceIds.length || (preview && !assets.length)) return;
    const controller = new AbortController(); operation.current = controller; setBusy(true); onLoading?.(true); setError("");
    if (!preview && !cursor) { onPreview(null); setAssets([]); setListing(null); }
    const intent = beginOperation?.() ?? 0;
    const isCurrent = () => !controller.signal.aborted && (isCurrentOperation?.(intent) ?? true);
    try {
      const scope = { configuration_version_id: versionId, workspace_ids: workspaceIds };
      if (preview) {
        const result = await previewEvaluationSources({ ...scope, asset_version_ids: assets }, controller.signal);
        if (!isCurrent()) return;
        if (result.complete !== true || result.document_count !== result.documents.length || result.evidence_count !== result.evidence.length) throw new Error("incomplete");
        onPreview(result);
      } else {
        const result = await listEvaluationDocuments({ ...scope, limit: 50, cursor: cursor ?? null }, controller.signal);
        if (!isCurrent()) return;
        setListing((current) => ({ ...result, documents: cursor ? [...(current?.documents ?? []), ...result.documents].filter((item, index, all) => all.findIndex((other) => other.asset_version_id === item.asset_version_id) === index) : result.documents }));
      }
    } catch {
      if (isCurrent()) setError("자료를 불러오지 못했습니다. 접근 권한, 활성·READY 상태, 기준선과 같은 처리·색인 조합을 확인하고 문서 범위를 줄여 다시 조회하세요. 부분 근거는 사용하지 않습니다.");
    } finally {
      if (!controller.signal.aborted) { operation.current = null; setBusy(false); onLoading?.(false); }
    }
  }
  return <section><h3>1. 구성과 평가 자료 선택</h3>
    <p>한 후보와 자동 BM25 기준선의 같은 문서 처리·색인 조합만 지원합니다. 조회는 평가나 모델 실행을 하지 않습니다.</p>
    <fieldset disabled={disabled}><legend>정확한 구성 버전과 지식 공간</legend>
      <label>평가할 구성<select value={versionId} onChange={(event) => { invalidate(true); setVersionId(event.target.value); }}>
        <option value="">구성 버전 선택</option>
        {candidates.map((item) => <option key={item.version_id} value={item.version_id}>{item.name} v{item.version}</option>)}
      </select></label>
      {workspaces.map((workspace) => <label key={workspace.id}><input type="checkbox" checked={workspaceIds.includes(workspace.id)} onChange={(event) => { invalidate(true); setWorkspaceIds((current) => event.target.checked ? [...current, workspace.id] : current.filter((id) => id !== workspace.id)); }} />{workspace.name}</label>)}
    </fieldset>
    <button type="button" disabled={disabled || busy || !versionId || !workspaceIds.length} onClick={() => void load(false)}>문서 목록 불러오기</button>
    {listing ? <fieldset disabled={disabled}><legend>평가할 문서 버전</legend>
      {listing.documents.map((document) => <label key={document.asset_version_id}><input type="checkbox" disabled={!document.ready} checked={assets.includes(document.asset_version_id)} onChange={(event) => { invalidate(false); setAssets((current) => event.target.checked ? [...current, document.asset_version_id] : current.filter((id) => id !== document.asset_version_id)); }} />{document.title} v{document.number}{!document.ready ? " (준비되지 않음)" : ""}</label>)}
      {!listing.documents.length ? <p>선택한 범위에 문서가 없습니다.</p> : null}
    </fieldset> : null}
    {listing?.next_cursor ? <button type="button" disabled={disabled || busy} onClick={() => void load(false, listing.next_cursor ?? undefined)}>문서 더 보기</button> : null}
    <button type="button" disabled={disabled || busy || !assets.length} onClick={() => void load(true)}>근거 불러오기</button>
    {busy ? <p role="status">자료 조회 중…</p> : null}{error ? <p role="alert">{error}</p> : null}
  </section>;
}
