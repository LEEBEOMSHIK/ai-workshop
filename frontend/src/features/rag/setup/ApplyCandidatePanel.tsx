import { useRef, useState } from "react";
import Link from "next/link";
import { Button } from "../../../shared/ui/Button";
import { ragDomainChatPath } from "../../../shared/routing/routes";
import { loadConfigurations, type SavedConfiguration, type Workspace } from "../configurations/api";
import { activateDomainConnection, createDomainConnection, listAdminDomains, listDomainConnections, type Domain } from "../domains/api";
import { canApplyCandidate } from "./candidate";
import styles from "./Setup.module.css";

interface Props { candidate:SavedConfiguration; domains:Domain[]; workspaces:Workspace[]; acceptedVersionId:string|null }
interface Preview { domain:Domain; activeId:string|null; workspaceIds:string[] }
const activeId = (domain:Domain)=>domain.active ? domain.connection_version?.id ?? null : null;
const sameScope = (left:string[],right:string[])=>left.length===right.length && left.every(id=>right.includes(id));
class SetupConflict extends Error {}
const failure = (cause:unknown) => cause instanceof SetupConflict ? cause.message : "요청 결과를 확인하지 못했습니다. 최신 상태를 확인한 뒤 다시 시도하세요.";

export function ApplyCandidatePanel({candidate,domains,workspaces,acceptedVersionId}:Props) {
  const [domainId,setDomainId] = useState("");
  const [preview,setPreview] = useState<Preview|null>(null);
  const [confirmed,setConfirmed] = useState(false);
  const [busy,setBusy] = useState(false);
  const pending = useRef(false);
  const [error,setError] = useState("");
  const [applied,setApplied] = useState<Domain|null>(null);
  const ready = canApplyCandidate(candidate) && acceptedVersionId===candidate.version_id;

  async function prepare() {
    if (!ready || !domainId || pending.current) return;
    pending.current=true;setBusy(true);setError("");setPreview(null);setConfirmed(false);setApplied(null);
    try {
      const [configs,latestDomains,history] = await Promise.all([loadConfigurations(),listAdminDomains(),listDomainConnections(domainId)]);
      const latest=configs.find(item=>item.version_id===candidate.version_id);
      const domain=latestDomains.find(item=>item.id===domainId);
      if (!latest || !canApplyCandidate(latest) || !domain) throw new SetupConflict("후보와 도메인의 최신 상태를 다시 확인하세요.");
      const current=history.find(item=>item.id===activeId(domain));
      if (activeId(domain) && !current) throw new SetupConflict("현재 대화 연결을 확인할 수 없습니다.");
      const workspaceIds=current ? current.workspace_ids : latest.workspace_ids;
      if (!workspaceIds.length || workspaceIds.some(id=>!latest.workspace_ids.includes(id))) throw new SetupConflict("기존 대화의 지식 공간을 이 후보가 모두 포함하지 않습니다. 적용 범위를 유지할 수 없어 중단했습니다.");
      setPreview({domain,activeId:activeId(domain),workspaceIds:[...workspaceIds]});
    } catch (cause) {setError(failure(cause));}
    finally {pending.current=false;setBusy(false);}
  }

  async function apply() {
    if (!preview||!confirmed||!ready||pending.current) return;
    pending.current=true;setBusy(true);setError("");
    try {
      const [configs,latestDomains] = await Promise.all([loadConfigurations(),listAdminDomains()]);
      const latest=configs.find(item=>item.version_id===candidate.version_id);
      const domain=latestDomains.find(item=>item.id===preview.domain.id);
      if (!latest||!canApplyCandidate(latest)||!domain||activeId(domain)!==preview.activeId) {
        setPreview(null);setConfirmed(false);throw new SetupConflict("확인 이후 설정이 변경됐습니다. 적용 내용을 다시 확인하세요.");
      }
      let history=await listDomainConnections(domain.id);
      let connection=history.find(item=>item.configuration_version_id===candidate.version_id && sameScope(item.workspace_ids,preview.workspaceIds));
      if (!connection) {
        history=await createDomainConnection(domain.id,{configuration_version_id:candidate.version_id,workspace_ids:preview.workspaceIds});
        connection=history.find(item=>item.configuration_version_id===candidate.version_id && sameScope(item.workspace_ids,preview.workspaceIds));
      }
      if (!connection) throw new SetupConflict("연결 저장 결과를 확인할 수 없습니다. 새로 확인한 뒤 다시 시도하세요.");
      const beforeActivate=(await listAdminDomains()).find(item=>item.id===domain.id);
      if (!beforeActivate || activeId(beforeActivate)!==preview.activeId) throw new SetupConflict("확인 이후 설정이 변경됐습니다. 적용 내용을 다시 확인하세요.");
      try {
        const saved=await activateDomainConnection(domain.id,connection.id);
        if (saved.active_connection_version_id!==connection.id) throw new SetupConflict("활성화 결과가 일치하지 않습니다. 최신 상태를 확인하세요.");
      } catch {
        const observed=(await listAdminDomains()).find(item=>item.id===domain.id);
        if (!observed || activeId(observed)!==connection.id) throw new SetupConflict("적용 완료를 확인하지 못했습니다. 현재 연결을 다시 확인하세요.");
      }
      setApplied(domain);setPreview(null);setConfirmed(false);
    } catch (cause) {
      setError(failure(cause));
      setPreview(null);setConfirmed(false);
    } finally {pending.current=false;setBusy(false);}
  }

  return <section className={styles.panel} aria-label="대화에 적용">
    <h2>4. 대화에 적용</h2>
    <p>선택한 도메인에 새 연결을 적용합니다. 기존 문서 범위를 유지하고 전체 기본값은 바꾸지 않습니다.</p>
    {!ready ? <p className={styles.notice}>답변 품질 평가에서 이 구성의 ‘통과 반영’을 완료하고 준비 상태를 새로 확인하세요. 이전에 통과했다면 기존 완료 평가에서 다시 반영할 수 있습니다. 이 확인은 새 답변을 생성하지 않습니다.</p> : null}
    <fieldset disabled={busy||!ready} className={styles.fields}>
      <label>적용할 대화<select value={domainId} onChange={event=>{setDomainId(event.target.value);setPreview(null);setConfirmed(false);setApplied(null);setError("");}}>
        <option value="">대화를 선택하세요</option>{domains.map(item=><option value={item.id} key={item.id}>{item.display_name}</option>)}
      </select></label>
      <Button onClick={()=>void prepare()} disabled={!domainId||busy||!ready}>적용 내용 확인</Button>
      {preview ? <div className={styles.summary}>
        <h3>{preview.domain.display_name}</h3><p>{candidate.name} · {candidate.generation_execution_preview?.model_name ?? "선택한 모델"}</p>
        <p>지식 공간: {preview.workspaceIds.map(id=>workspaces.find(item=>item.id===id)?.name??"조회 불가").join(" · ")}</p>
        <label className={styles.check}><input type="checkbox" checked={confirmed} onChange={event=>setConfirmed(event.target.checked)} />이 대화를 사용하는 사용자에게 새 모델을 적용합니다.</label>
        <Button variant="primary" disabled={!confirmed||busy} onClick={()=>void apply()}>{busy?"적용 중…":"이 대화에 적용"}</Button>
      </div> : null}
    </fieldset>
    {error?<p role="alert">{error} 저장된 비활성 연결은 다음 확인에서 재사용합니다.</p>:null}
    {applied?<p role="status">{applied.display_name}에 적용했습니다. <Link href={ragDomainChatPath(applied.slug)}>대화 열기</Link></p>:null}
  </section>;
}
