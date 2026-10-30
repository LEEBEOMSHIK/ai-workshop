import { useRef, useState } from "react";
import { Button } from "../../../shared/ui/Button";
import { loadModelLab, registerGenerationProfile, type DeploymentSummary, type ProfileSummary } from "../models/api";
import { loadConfigurations, saveConfiguration, type SavedConfiguration, type Workspace } from "../configurations/api";
import { candidateRequest, compatibleAnswerSettings, externalDisclosureVersion, sameJson } from "./candidate";
import type { SetupOptions } from "./setup-api";
import styles from "./Setup.module.css";

interface Props {
  deployment: DeploymentSummary;
  configurations: SavedConfiguration[];
  profiles: ProfileSummary[];
  workspaces: Workspace[];
  options: SetupOptions;
  onSaved: (candidate: SavedConfiguration, profile: ProfileSummary) => void;
}

export function RagCandidatePanel({deployment,configurations,profiles,workspaces,options,onSaved}: Props) {
  const [baseId,setBaseId] = useState("");
  const [sourceId,setSourceId] = useState("");
  const [name,setName] = useState("");
  const [approved,setApproved] = useState(false);
  const [generationConfirmed,setGenerationConfirmed] = useState(false);
  const [busy,setBusy] = useState(false);
  const pending = useRef(false);
  const [error,setError] = useState("");
  const [savedProfile,setSavedProfile] = useState<{fingerprint:string; profile:ProfileSummary}|null>(null);
  const [uncertain,setUncertain] = useState(false);
  const [completed,setCompleted] = useState("");
  const base = configurations.find(item=>item.version_id === baseId);
  const generationProfiles = profiles.filter(item=>item.kind === "generation" && !item.legacy && item.deployment_version_id);
  const selectedSourceId = sourceId || (base?.generation_profile_id ? `profile:${base.generation_profile_id}` : "");
  const source = generationProfiles.find(item=>`profile:${item.id}` === selectedSourceId);
  const preset = options.generation_presets.find(item=>`preset:${item.id}` === selectedSourceId);
  const settings = source?.config ?? preset?.config;
  const compatible = settings && compatibleAnswerSettings(settings,deployment);
  const disclosureVersion = externalDisclosureVersion(deployment.provider);
  const candidateName = name.trim() || (base ? `${base.name} · ${deployment.display_name}`.slice(0,140) : "");
  const fingerprint = JSON.stringify([deployment.version_id,candidateName,settings]);
  const saveFingerprint = JSON.stringify([fingerprint,baseId]);
  const alreadySaved = completed===saveFingerprint;
  const reusable = source?.deployment_version_id === deployment.version_id ? source :
    savedProfile?.fingerprint === fingerprint ? savedProfile.profile : null;

  function changeSelection(change:()=>void) {
    change(); setApproved(false); setGenerationConfirmed(false); setError("");
  }

  async function save() {
    if (pending.current || !base || !settings || !compatible || !candidateName || uncertain || alreadySaved
      || (base.answer_policy.mode !== "generative" && !generationConfirmed)
      || (deployment.external_transfer && (!approved || !disclosureVersion))) return;
    pending.current=true; setBusy(true); setError("");
    let profile = reusable;
    let stage: "profile"|"configuration" = "profile";
    try {
      if (!profile) {
        profile = await registerGenerationProfile({name:`${candidateName} · 답변`,version:1,
          deployment_version_id:deployment.version_id, bindings:[], evaluation_state:"draft",
          config:structuredClone(settings)});
        setSavedProfile({fingerprint,profile});
      }
      stage="configuration";
      const candidate = await saveConfiguration(candidateRequest(base,candidateName,profile.id,
        deployment.external_transfer ? {confirmed:true,disclosure_version:disclosureVersion!} : undefined));
      setCompleted(saveFingerprint);onSaved(candidate,profile);
    } catch {
      // A lost response can follow a committed write. Reconcile before allowing another save.
      try {
        const [lab, saved] = await Promise.all([loadModelLab(),loadConfigurations()]);
        profile = profile ?? lab.profiles.find(item=>item.name === `${candidateName} · 답변` && item.version===1
          && item.deployment_version_id===deployment.version_id && sameJson(item.config,settings)) ?? null;
        if (profile) setSavedProfile({fingerprint,profile});
        const expected = profile ? candidateRequest(base,candidateName,profile.id) : null;
        const recovered = expected ? saved.find(item=>item.name===expected.name && item.generation_profile_id===expected.generation_profile_id
          && item.document_processing_profile_id===expected.document_processing_profile_id && item.indexing_profile_id===expected.indexing_profile_id
          && item.retrieval_profile_id===expected.retrieval_profile_id && sameJson([...item.workspace_ids].sort(),[...expected.workspace_ids].sort())
          && item.answer_policy.min_keyword_coverage===expected.answer_policy.min_keyword_coverage
          && item.answer_policy.min_semantic_score===expected.answer_policy.min_semantic_score
          && item.answer_policy.mode==="generative" && item.answer_policy.require_complete_provenance===expected.answer_policy.require_complete_provenance
          && item.answer_policy.conflict_mode===expected.answer_policy.conflict_mode) : undefined;
        if (stage === "configuration" && recovered && profile) { setCompleted(saveFingerprint);onSaved(recovered,profile); return; }
        setError(profile ? "답변 설정은 저장되어 재사용됩니다. RAG 후보 저장에 실패했습니다. 입력과 정책을 확인한 뒤 다시 시도하세요."
          : "답변 설정을 저장하지 못했습니다. 선택한 모델과 설정의 호환성을 확인하세요.");
      } catch {
        setUncertain(true); setError("저장 결과를 확인하지 못했습니다. 중복 생성을 막기 위해 재저장을 중단했습니다. 목록을 새로 불러와 저장 여부를 확인하세요.");
      }
    } finally { pending.current=false; setBusy(false); }
  }

  return <section className={styles.panel} aria-label="RAG 후보 만들기">
    <h2>2. 기존 RAG 설정 가져오기</h2>
    <p>문서 처리·검색 방식·인용 규칙·지식 공간을 가져와 새 모델의 시험 구성을 만듭니다.</p>
    <fieldset disabled={busy || uncertain} className={styles.fields}>
      <label>기반 RAG 구성<select value={baseId} onChange={event=>changeSelection(()=>{setBaseId(event.target.value);setSourceId("");})}>
        <option value="">가져올 구성을 선택하세요</option>
        {configurations.map(item=><option key={item.version_id} value={item.version_id}>{item.name} · v{item.version}{item.is_default ? " · 현재 기본값" : ""}</option>)}
      </select></label>
      {base ? <>
        <div className={styles.summary}><strong>유지할 검색 범위</strong><p>{base.workspace_ids.map(id=>workspaces.find(w=>w.id===id)?.name ?? "조회할 수 없는 지식 공간").join(" · ")}</p>
          <p>검색·임베딩·문서 처리 유지 · 인용 검증 필수</p></div>
        <label>후보 이름<input value={name} onChange={event=>setName(event.target.value)} placeholder={candidateName} maxLength={140} /></label>
        <label>답변 설정<select value={selectedSourceId} onChange={event=>changeSelection(()=>setSourceId(event.target.value))}>
          <option value="">답변 설정을 선택하세요</option>
          <optgroup label="기존 답변 설정 그대로 사용">{generationProfiles.map(item=><option key={item.id} value={`profile:${item.id}`}>{item.name} · v{item.version}</option>)}</optgroup>
          <optgroup label="새 모델용 기본 후보">{options.generation_presets.filter(item=>item.supported_providers.includes(deployment.provider)).map(item=><option key={item.id} value={`preset:${item.id}`}>{item.name}</option>)}</optgroup>
        </select></label>
        {preset ? <p className={styles.notice}>{preset.description} 기존 답변 설정과 다르므로 새 품질 평가가 필요합니다.</p> : null}
        {base.answer_policy.mode !== "generative" ? <label className={styles.check}><input type="checkbox" checked={generationConfirmed} onChange={event=>setGenerationConfirmed(event.target.checked)} />
          이 후보에서 추출식 답변을 LLM 생성 답변으로 변경합니다. 검색·인용 규칙은 유지하며 기존 구성에는 영향을 주지 않습니다.
        </label> : null}
        {settings && !compatible ? <p role="alert">이 답변 설정은 선택한 공급자와 호환되지 않습니다. 호환되는 기존 설정 또는 해당 모델용 기본 후보를 선택하세요. 기존 설정을 자동 변환하지 않습니다.</p> : null}
        {deployment.external_transfer ? <label className={styles.check}><input type="checkbox" checked={approved} onChange={event=>setApproved(event.target.checked)} />
          {deployment.provider === "anthropic_messages" ? "Anthropic" : "OpenAI"}의 {deployment.provider_model_id} 외부 API로 질문·제한된 대화·선별 원문 근거·서비스 지침이 전송됨을 확인했습니다. 선택한 지식 공간의 외부 전송 정책도 적용됩니다.
        </label> : null}
      </> : null}
    </fieldset>
    {!configurations.length ? <p>먼저 고급 RAG 구성에서 검색 기준 구성을 저장하세요.</p> : null}
    <Button variant="primary" onClick={()=>void save()} disabled={busy||uncertain||alreadySaved||!base||!compatible||(base.answer_policy.mode!=="generative"&&!generationConfirmed)||(deployment.external_transfer&&(!approved||!disclosureVersion))}>{busy?"후보 저장 중…":alreadySaved?"시험 구성 저장 완료":"시험 구성 저장"}</Button>
    {savedProfile ? <p role="status">답변 설정 저장 완료. 같은 입력으로 다시 저장하면 이 설정을 재사용합니다.</p> : null}
    {error ? <p role="alert">{error}</p> : null}
  </section>;
}
