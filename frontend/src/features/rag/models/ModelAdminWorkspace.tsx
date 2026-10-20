import { type ReactNode } from "react";
import { routes } from "../../../shared/routing/routes";
import { ModelAdminTabs } from "./ModelAdminTabs";
import { DeploymentRegistry } from "./DeploymentRegistry";
import { LlmModelForm } from "./LlmModelForm";
import { HttpDeploymentForm } from "./HttpDeploymentForm";
import { HttpGenerationForm } from "./HttpGenerationForm";
import { DataPolicyPanel } from "./DataPolicyPanel";
import styles from "./ModelAdmin.module.css";
import { type ModelAdministrationData, type ModelDefinitionSummary, type DeploymentSummary, type ProfileSummary } from "./api";

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
      <section aria-label="HTTP 실행 환경">
        <HttpDeploymentForm models={props.models} onSaved={props.onDeploymentSaved} />
        <p>등록된 HTTP 배포에서 상태를 확인한 뒤 생성 프로파일을 연결하세요. 외부 OpenAI Responses API 배포는 기존 등록 정보와 상태를 확인할 수 있습니다.</p>
        {administration ? <DeploymentRegistry deployments={administration.deployments.filter((deployment) => deployment.provider !== "development_codex_exec")} /> : null}
      </section>
    </div>,
    <div key="profiles">
      <h2>문서 처리부터 답변까지 구성</h2>
      <p>문서 처리 → 색인 → 검색 → 답변 순서로 프로파일을 확인하고 새 불변 버전을 등록합니다. 연결과 평가는 저장 구성에서 별도로 확인합니다.</p>
      {props.workflowProfiles}
      <h2>답변 생성 프로파일 등록</h2>
      <section aria-label="HTTP 답변 설정">
        {administration ? <HttpGenerationForm deployments={administration.deployments} onSaved={props.onProfileSaved} /> : <p>배포 목록을 불러온 뒤 HTTP 생성 폼이 표시됩니다.</p>}
      </section>
      <p><a href={routes.adminRagConfigurations}>RAG 구성 스튜디오에서 프로파일 연결하기</a></p>
      <details><summary>고급 프로파일 YAML 등록</summary>{props.profileForm}</details>
    </div>,
    <div key="policy">
      <p>선택만으로 데이터 사용 정책을 저장하거나 외부에 전송하지 않습니다.</p>
      {administration ? <DataPolicyPanel installationPolicy={administration.installationPolicy}
        workspaces={administration.workspaces} workspacePolicies={administration.workspacePolicies} /> : null}
    </div>,
    <div key="verification">
      <h2>저장 구성 연결 검사와 사용 준비</h2>
      <p>프로파일을 등록한 것만으로 활성화되지 않습니다. 저장 구성에서 프로파일과 배포를 연결하고, 해당 구성 버전의 검색·답변 준비 상태 및 실제 검색 평가 상태를 확인하세요.</p>
      <a className={styles.actionLink} href={routes.adminRagConfigurations}>저장 구성에서 연결 검사하기</a>
    </div>,
  ]} />;
}
