import { useState, type ReactNode } from "react";
import { routes } from "../../../shared/routing/routes";
import { ModelAdminTabs } from "./ModelAdminTabs";
import { DeploymentRegistry } from "./DeploymentRegistry";
import { CodexSetup } from "./CodexSetup";
import { LlmModelForm } from "./LlmModelForm";
import { CodexGenerationForm } from "./CodexGenerationForm";
import { CodexEvidenceApproval } from "./CodexEvidenceApproval";
import { DataPolicyPanel } from "./DataPolicyPanel";
import styles from "./ModelAdmin.module.css";
import { codexError, loadCodexRunners, type CodexRunner, type ModelAdministrationData, type ModelDefinitionSummary, type DeploymentSummary, type ProfileSummary } from "./api";

interface Props {
  models: ModelDefinitionSummary[];
  administration: ModelAdministrationData | null;
  modelRegistry: ReactNode; profileRegistry: ReactNode; workflowProfiles: ReactNode;
  modelForm: ReactNode; profileForm: ReactNode;
  onModelSaved: (model: ModelDefinitionSummary) => void;
  onDeploymentSaved: (deployment: DeploymentSummary) => void;
  onProfileSaved: (profile: ProfileSummary) => void;
}

export function ModelAdminWorkspace(props: Props) {
  const { administration } = props;
  const [provider, setProvider] = useState("http");
  const [runners, setRunners] = useState<CodexRunner[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  async function loadRunners() {
    if (loading) return;
    setLoading(true); setError("");
    try { setRunners(await loadCodexRunners()); }
    catch (failure) { setError(codexError(failure)); }
    finally { setLoading(false); }
  }
  return <ModelAdminTabs panels={[
    <div key="overview">
      <p>등록된 버전과 기록을 조회합니다. 이 목록은 현재 검색에 연결되었거나 사용 준비가 완료되었다는 뜻이 아닙니다.</p>
      {props.modelRegistry}{props.profileRegistry}
      {administration ? <DeploymentRegistry deployments={administration.deployments} readOnly /> : null}
    </div>,
    <div key="setup">
      <h2>모델과 실행 환경 등록</h2>
      <p>모델 정의를 먼저 등록한 다음 실행 배포에 연결합니다. 등록은 모델 실행이나 사용 승격이 아닙니다.</p>
      <LlmModelForm onSaved={props.onModelSaved} />
      <details><summary>고급 모델 정의 JSON 등록</summary>{props.modelForm}</details>
      <h2>공급자별 실행 환경</h2>
      <label>설정할 실행 환경<select value={provider} onChange={(event) => setProvider(event.target.value)}>
        <option value="http">로컬·사내 OpenAI 호환 / OpenAI Responses API</option>
        <option value="development_codex_exec">개발용 Codex CLI</option>
      </select></label>
      <section hidden={provider !== "http"} aria-label="HTTP 실행 환경">
        <p>이 화면에서는 기존 로컬·사내 OpenAI 호환 및 OpenAI Responses API 배포의 등록 정보와 상태를 확인합니다. HTTP 배포 신규 등록 폼은 제공하지 않습니다.</p>
        {administration ? <DeploymentRegistry deployments={administration.deployments.filter((deployment) => deployment.provider !== "development_codex_exec")} /> : null}
      </section>
      <section hidden={provider !== "development_codex_exec"} aria-label="Codex 실행 환경">
        <CodexSetup models={props.models} runners={runners} loading={loading} error={error}
          onLoad={() => void loadRunners()} onDeploymentSaved={props.onDeploymentSaved} />
        {administration ? <DeploymentRegistry deployments={administration.deployments.filter((deployment) => deployment.provider === "development_codex_exec")} /> : null}
      </section>
    </div>,
    <div key="profiles">
      <h2>문서 처리부터 답변까지 구성</h2>
      <p>문서 처리 → 색인 → 검색 → 답변 순서로 프로파일을 확인하고 새 불변 버전을 등록합니다. 연결과 평가는 저장 구성에서 별도로 확인합니다.</p>
      {props.workflowProfiles}
      <h2>답변 생성 프로파일 등록</h2>
      <p>Codex 답변을 구성하려면 먼저 ‘모델·실행 환경 설정’에서 LLM 정의와 Codex 배포를 등록하고 서버 Codex 설정을 불러오세요.</p>
      {runners && administration ? <CodexGenerationForm deployments={administration.deployments} runners={runners} onSaved={props.onProfileSaved} /> : <p>서버 Codex 설정을 불러온 뒤 생성 폼이 표시됩니다.</p>}
      <details><summary>고급 프로파일 YAML 등록</summary>{props.profileForm}</details>
    </div>,
    <div key="policy">
      <p>데이터 사용 정책과 문서 revision 승인은 별도 절차입니다. 선택만으로 저장하거나 외부에 전송하지 않습니다.</p>
      {administration ? <><DataPolicyPanel installationPolicy={administration.installationPolicy}
        workspaces={administration.workspaces} workspacePolicies={administration.workspacePolicies} />
        <CodexEvidenceApproval workspaces={administration.workspaces} /></> : null}
    </div>,
    <div key="verification">
      <h2>저장 구성 연결 검사와 사용 준비</h2>
      <p>프로파일을 등록한 것만으로 활성화되지 않습니다. 저장 구성에서 프로파일과 배포를 연결하고, 해당 구성 버전의 명시 연결 검사 및 실제 검색 평가 상태를 확인하세요.</p>
      <p>Codex 연결 검사는 실행을 포함합니다. 저장 구성 화면의 입력·모델 고지를 확인한 뒤 명시적으로 요청하세요. 이 탭은 검사를 자동 실행하지 않습니다.</p>
      <a className={styles.actionLink} href={routes.adminRagConfigurations}>저장 구성에서 연결 검사하기</a>
    </div>,
  ]} />;
}
