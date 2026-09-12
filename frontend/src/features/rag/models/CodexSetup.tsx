import { CodexDeploymentForm } from "./CodexDeploymentForm";
import type { CodexRunner, DeploymentSummary, ModelDefinitionSummary } from "./api";

export function CodexSetup({ models, runners, loading, error, onLoad, onDeploymentSaved }: {
  models: ModelDefinitionSummary[]; runners: CodexRunner[] | null;
  loading: boolean; error: string; onLoad: () => void;
  onDeploymentSaved: (deployment: DeploymentSummary) => void;
}) {
  return <section className="registry-group" aria-label="개인 Codex 설정">
    <h3>개발용 Codex 배포 등록</h3>
    <p>위에서 등록한 LLM 정의를 서버 runner에 연결합니다. 설정 조회는 모델을 호출하지 않으며, 불러온 runner 목록을 답변 생성 프로파일에서도 공유합니다.</p>
    <button type="button" disabled={loading} onClick={onLoad}>서버 Codex 설정 불러오기</button>
    {error ? <p role="alert">{error}</p> : null}
    {runners ? <CodexDeploymentForm runners={runners} models={models} onSaved={onDeploymentSaved} /> : null}
  </section>;
}
