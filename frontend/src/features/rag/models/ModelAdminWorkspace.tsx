import { useState, type ReactNode } from "react";
import { routes } from "../../../shared/routing/routes";
import { Button } from "../../../shared/ui/Button";
import { ChoiceGroup } from "../../../shared/ui/ChoiceGroup";
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
  const [selected, setSelected] = useState(0);
  const [connectionTask, setConnectionTask] = useState("model");
  const [profileTask, setProfileTask] = useState("registered");
  const [jsonExpanded, setJsonExpanded] = useState(false);
  return <ModelAdminTabs selected={selected} onSelect={setSelected} panels={[
    <div key="overview">
      <div className={styles.overviewHeading}>
        <h2>필요한 관리 작업부터 시작하세요</h2>
        <p>연결을 처음 준비한다면 상단의 간편 설정을 이용하세요. 여기서는 개별 모델·배포·프로파일의 불변 버전을 관리합니다.</p>
      </div>
      <div className={styles.taskCards}>
        <article><h3>모델과 실행 배포</h3><p>모델 정의를 등록하고 실행 환경에 연결합니다.</p><Button onClick={() => setSelected(1)}>모델 연결 작업 열기</Button></article>
        <article><h3>문서 처리부터 답변까지</h3><p>등록된 프로파일을 확인하거나 새 버전을 만듭니다.</p><Button onClick={() => setSelected(2)}>처리 설정 작업 열기</Button></article>
        <article><h3>데이터 사용 범위</h3><p>회사와 지식 공간의 외부 전송 정책을 확인합니다.</p><Button onClick={() => setSelected(3)}>데이터 정책 열기</Button></article>
      </div>
      <section className={styles.guidance} aria-label="연결 검사 안내">
        <h3>등록 다음에는 연결과 평가를 확인하세요</h3>
        <p>등록만으로 활성화되지 않습니다. 저장 구성에서 해당 버전의 검색·답변 준비 상태와 평가 결과를 확인하세요.</p>
        <a className={styles.actionLink} href={routes.adminRagConfigurations}>저장 구성에서 연결 검사하기</a>
      </section>
      <p>등록된 버전과 기록을 조회합니다. 이 목록은 현재 검색에 연결되었거나 사용 준비가 완료되었다는 뜻이 아닙니다.</p>
      <details className={styles.registryDetails}><summary>모델 정의 목록 · {props.models.length}개 버전</summary>{props.modelRegistry}</details>
      <details className={styles.registryDetails}><summary>프로파일 목록</summary>{props.profileRegistry}</details>
      <details className={styles.registryDetails}><summary>실행 배포와 과거 기록{administration ? ` · ${administration.deployments.length}개 버전` : ""}</summary>
        {administration ? <DeploymentRegistry deployments={administration.deployments} readOnly /> : <p>실행 배포 정보를 불러온 뒤 표시됩니다.</p>}
      </details>
    </div>,
    <div key="setup">
      <h2>모델과 실행 환경 등록</h2>
      <p>모델 정의를 먼저 등록한 다음 실행 배포에 연결합니다. 등록은 모델 실행이나 사용 승격이 아닙니다.</p>
      <ChoiceGroup legend="모델 연결 작업" variant="segmented" value={connectionTask} onChange={setConnectionTask}
        options={[{ value: "model", label: "모델 정의 등록" }, { value: "deployment", label: "실행 배포 등록" }, { value: "registered", label: "등록 배포 확인" }]} />
      <div hidden={connectionTask !== "model"} className={styles.taskContent}>
        <div hidden={jsonExpanded}><LlmModelForm onSaved={props.onModelSaved} /></div>
        <details onToggle={(event) => setJsonExpanded(event.currentTarget.open)}>
          <summary>고급 모델 정의 JSON 등록</summary>
          <p>임베딩·리랭커·OCR 등 전체 모델 종류를 등록합니다. 접으면 LLM 식별자 입력으로 돌아갑니다. 입력 중인 값은 유지됩니다.</p>
          {props.modelForm}
        </details>
      </div>
      <section aria-label="HTTP 실행 환경" hidden={connectionTask !== "deployment"}>
        <HttpDeploymentForm models={props.models} onSaved={props.onDeploymentSaved} />
      </section>
      <section aria-label="등록 배포 확인" hidden={connectionTask !== "registered"}>
        <p>등록된 배포의 상태를 직접 확인한 뒤 생성 프로파일을 연결하세요. 상태 확인은 버튼을 누를 때 실행됩니다.</p>
        {administration ? <DeploymentRegistry deployments={administration.deployments.filter((deployment) => deployment.provider !== "development_codex_exec")} /> : null}
      </section>
    </div>,
    <div key="profiles">
      <h2>문서 처리부터 답변까지 구성</h2>
      <p>문서 처리 → 색인 → 검색 → 답변 순서로 프로파일을 확인하고 새 불변 버전을 등록합니다. 연결과 평가는 저장 구성에서 별도로 확인합니다.</p>
      <ChoiceGroup legend="처리 설정 작업" variant="segmented" value={profileTask} onChange={setProfileTask}
        options={[{ value: "registered", label: "등록 프로파일 확인" }, { value: "generation", label: "답변 생성 설정" }, { value: "yaml", label: "YAML로 등록 · 고급" }]} />
      <div hidden={profileTask !== "registered"}>{props.workflowProfiles}</div>
      <section aria-label="HTTP 답변 설정" hidden={profileTask !== "generation"}>
        <h2>답변 생성 프로파일 등록</h2>
        {administration ? <HttpGenerationForm deployments={administration.deployments} onSaved={props.onProfileSaved} /> : <p>배포 목록을 불러온 뒤 HTTP 생성 폼이 표시됩니다.</p>}
      </section>
      <div hidden={profileTask !== "yaml"}><details><summary>고급 프로파일 YAML 등록</summary>{props.profileForm}</details></div>
      <p><a href={routes.adminRagConfigurations}>RAG 구성 스튜디오에서 프로파일 연결하기</a></p>
    </div>,
    <div key="policy">
      <p>선택만으로 데이터 사용 정책을 저장하거나 외부에 전송하지 않습니다.</p>
      {administration ? <DataPolicyPanel installationPolicy={administration.installationPolicy}
        workspaces={administration.workspaces} workspacePolicies={administration.workspacePolicies} /> : null}
    </div>,
  ]} />;
}
