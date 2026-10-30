"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { apiRequest } from "../../../shared/api/client";
import { routes } from "../../../shared/routing/routes";
import { Button } from "../../../shared/ui/Button";
import { loadConfigurations, type SavedConfiguration, type Workspace } from "../configurations/api";
import { GenerativeEvaluationPanel } from "../configurations/GenerativeEvaluationPanel";
import { listAdminDomains, type Domain } from "../domains/api";
import { loadModelLab, loadDeployments, checkDeploymentHealth, type ModelLabData, type DeploymentSummary } from "../models/api";
import { ModelConnectionPanel } from "./ModelConnectionPanel";
import { RagCandidatePanel } from "./RagCandidatePanel";
import { ApplyCandidatePanel } from "./ApplyCandidatePanel";
import { loadSetupOptions, type SetupOptions } from "./setup-api";
import styles from "./Setup.module.css";

export interface ModelSetupData extends ModelLabData {
  configurations:SavedConfiguration[]; deployments:DeploymentSummary[];
  domains:Domain[]; workspaces:Workspace[]; options:SetupOptions;
}
async function loadData():Promise<ModelSetupData> {
  const [lab,configurations,deployments,domains,workspaces,options] = await Promise.all([
    loadModelLab(),loadConfigurations(),loadDeployments(),listAdminDomains(),
    apiRequest<Workspace[]>("/api/v1/workspaces"),loadSetupOptions(),
  ]);
  return {...lab,configurations,deployments,domains,workspaces,options};
}
const upsert = <T,>(items:T[], item:T, key:(value:T)=>string) => [...items.filter(value=>key(value)!==key(item)),item];

export function ModelSetupPage({initialData}:{initialData?:ModelSetupData}) {
  const [data,setData]=useState(initialData);
  const [reload,setReload]=useState(0);
  const [loading,setLoading]=useState(!initialData);
  const [error,setError]=useState("");
  const [selectedId,setSelectedId]=useState("");
  const selectedRef=useRef("");
  const [candidateId,setCandidateId]=useState("");
  const [acceptedId,setAcceptedId]=useState<string|null>(null);
  const [evaluationOpen,setEvaluationOpen]=useState(false);
  const [checking,setChecking]=useState(false);
  const checkPending=useRef(false);
  const [healthMessage,setHealthMessage]=useState("");
  const [savedMessage,setSavedMessage]=useState("");

  useEffect(()=>{
    if (initialData && reload===0) return;
    let active=true;
    void loadData().then(value=>{if(active){setData(value);setError("");}})
      .catch(()=>{if(active)setError("설정 목록을 불러오지 못했습니다. 로그인·서버 상태를 확인한 뒤 다시 시도하세요.");})
      .finally(()=>{if(active)setLoading(false);});
    return ()=>{active=false;};
  },[initialData,reload]);

  function refresh(){setLoading(true);setReload(value=>value+1);}
  function selectDeployment(id:string) {
    selectedRef.current=id;setSelectedId(id);setCandidateId("");setAcceptedId(null);
    setEvaluationOpen(false);setHealthMessage("");setSavedMessage("");
  }
  function selectCandidate(id:string){setCandidateId(id);setAcceptedId(null);setEvaluationOpen(false);}
  const deployment=data?.deployments.find(item=>item.version_id===selectedId);
  const candidates=data?.configurations.filter(item=>data.profiles.some(profile=>profile.id===item.generation_profile_id && profile.deployment_version_id===selectedId))??[];
  const candidate=candidates.find(item=>item.version_id===candidateId);

  async function checkConnection() {
    if (!deployment||checkPending.current) return;
    const id=deployment.version_id;
    checkPending.current=true;setChecking(true);setHealthMessage("");
    try {
      const result=await checkDeploymentHealth(id);
      const [deployments,configurations]=await Promise.all([loadDeployments(),loadConfigurations()]);
      setData(current=>current?{...current,deployments,configurations}:current);
      if(selectedRef.current===id)setHealthMessage(result.status==="ready"?"연결 확인 완료. 답변·인용 품질은 별도 평가가 필요합니다.":"연결이 준비되지 않았습니다. 모델 상태와 서버 연결 설정을 확인하세요.");
    } catch {if(selectedRef.current===id)setHealthMessage("연결 확인 결과를 가져오지 못했습니다. 서버 설정을 확인하세요.");}
    finally {checkPending.current=false;setChecking(false);}
  }

  return <main className={styles.page}>
    <header className={styles.header}><p className="eyebrow">MODEL & RAG SETUP</p><h1>모델 연결·RAG 설정</h1>
      <p>사용할 모델을 연결하고, 기존 검색 설정을 가져와 검증한 뒤 대화에 적용하세요.</p>
      <nav className={styles.links} aria-label="고급 설정"><Link href={routes.adminRagModels}>모델·서버 고급 설정</Link><Link href={routes.adminRagConfigurations}>RAG 구성·평가 전체</Link><Link href={routes.adminRagDomains}>도메인 연결 이력</Link></nav>
    </header>
    <ol className={styles.steps} aria-label="설정 순서">{["모델 연결·선택","RAG 설정 가져오기","연결·답변 검증","대화에 적용"].map((label,index)=><li key={label}><span>{index+1}</span>{label}</li>)}</ol>
    {loading?<p role="status">최신 설정을 확인하고 있습니다…</p>:null}
    {error?<p role="alert">{error}</p>:null}
    <div><Button onClick={refresh} disabled={loading}>설정 목록 새로 확인</Button></div>
    {data?<>
      <ModelConnectionPanel models={data.models} deployments={data.deployments} selectedDeploymentId={selectedId}
        onModelSaved={model=>setData(current=>current?{...current,models:upsert(current.models,model,item=>item.id)}:current)}
        onDeploymentSaved={saved=>setData(current=>current?{...current,deployments:upsert(current.deployments,saved,item=>item.version_id)}:current)}
        onSelectDeployment={selectDeployment}/>
      {deployment?<>
        <RagCandidatePanel key={deployment.version_id} deployment={deployment} configurations={data.configurations} profiles={data.profiles} workspaces={data.workspaces} options={data.options}
          onSaved={(saved,profile)=>{
            setData(current=>current?{...current,profiles:upsert(current.profiles,profile,item=>item.id),configurations:upsert(current.configurations,saved,item=>item.version_id)}:current);
            if(selectedRef.current===profile.deployment_version_id){selectCandidate(saved.version_id);setSavedMessage("시험 구성을 저장했습니다. 연결과 답변 품질을 확인해 주세요.");}
          }}/>
        <section className={styles.panel} aria-label="연결과 답변 검증"><h2>3. 연결·답변 검증</h2>
          <p>연결 상태와 답변 품질을 각각 확인합니다. 모델이 응답하더라도 인용·정답 평가를 통과해야 적용할 수 있습니다.</p>
          <div className={styles.summary}><strong>{deployment.display_name} · {deployment.provider_model_id}</strong>
            <p>최근 연결: {deployment.latest_health?.status==="ready"?"정상":deployment.latest_health?"확인 필요":"미확인"}{deployment.latest_health?` · ${new Date(deployment.latest_health.checked_at).toLocaleString("ko-KR")}`:""}</p>
            <Button onClick={()=>void checkConnection()} disabled={checking}>{checking?"연결 확인 중…":"모델 연결 확인"}</Button>
            {healthMessage?<p role="status">{healthMessage}</p>:null}
          </div>
          {savedMessage?<p role="status">{savedMessage}</p>:null}
          <label>검증할 시험 구성<select value={candidateId} onChange={event=>selectCandidate(event.target.value)}>
            <option value="">저장한 구성을 선택하세요</option>{candidates.map(item=><option key={item.version_id} value={item.version_id}>{item.name} · v{item.version}</option>)}
          </select></label>
          {candidate?<>
            <ul className={styles.status}><li>검색 준비 {candidate.search_ready?"완료":"미완료"}</li><li>답변 준비 {candidate.answer_ready?"완료":"미완료"}</li><li>답변 품질 통과 반영 {acceptedId===candidate.version_id?"확인":"확인 필요"}</li></ul>
            <p>답변·인용·정답을 확인하고 해당 구성의 ‘통과 반영’을 실행하세요. 실제 모델 호출은 평가 실행 버튼을 누를 때 시작됩니다.</p>
            <Button onClick={()=>setEvaluationOpen(value=>!value)} aria-expanded={evaluationOpen}>{evaluationOpen?"답변 평가 접기":"답변 평가 열기"}</Button>
            <div hidden={!evaluationOpen}>{evaluationOpen?<GenerativeEvaluationPanel key={candidate.version_id} configurations={[candidate]} workspaces={data.workspaces} initialVersionIds={[candidate.version_id]} allowedVersionIds={[candidate.version_id]}
              onAccepted={receipt=>{if(receipt.configuration_version_id===candidate.version_id)setAcceptedId(receipt.configuration_version_id);}}
              onConfigurationUpdated={updated=>setData(current=>current?{...current,configurations:upsert(current.configurations,updated,item=>item.version_id)}:current)}/>:null}</div>
          </>:<p className={styles.notice}>위에서 시험 구성을 저장하거나 이 모델로 이미 저장된 구성을 선택하세요.</p>}
        </section>
        {candidate?<ApplyCandidatePanel key={candidate.version_id} candidate={candidate} domains={data.domains} workspaces={data.workspaces} acceptedVersionId={acceptedId}/>:null}
      </>:<section className={styles.panel}><h2>기존 설정으로 시작하세요</h2><p>1단계에서 연결을 선택하면 현재 RAG 설정을 가져올 수 있습니다. 새 후보를 검증하고 적용하기 전까지 기존 대화 설정이 유지됩니다.</p></section>}
    </>:null}
  </main>;
}
