import type { Domain } from "../domains/api";
import { CodexModelIdentity } from "./CodexModelIdentity";

export function ProcessingDisclosure({ domain }: { domain: Domain }) {
  const preview = domain.generation_execution_preview;
  if (!preview) {
    return <aside className="processing-disclosure" role="status"><p>모델과 처리 위치를 확인할 수 없어 질문을 보낼 수 없습니다.</p></aside>;
  }
  const providers = { local_openai_compatible: "로컬 OpenAI 호환", openai_responses: "OpenAI Responses API", development_codex_exec: "개발용 Codex CLI (외부 처리)" } as const;
  const locations = { local: "로컬", on_premise: "사내 온프레미스", external: "외부 API" } as const;
  return (
    <aside className="processing-disclosure" role="status" aria-label="질문 처리 안내">
      <p>{preview.disclosure}</p>
      <CodexModelIdentity execution={preview} />
      <details>
        <summary>모델 및 처리 위치 상세</summary>
        <dl className="identity-list">
          <div><dt>모델</dt><dd>{preview.model_name} 버전 {preview.model_version}</dd></div>
          <div><dt>공급자</dt><dd>{providers[preview.provider]}</dd></div>
          <div><dt>처리 위치</dt><dd>{locations[preview.location]}</dd></div>
          <div><dt>외부 전송</dt><dd>{preview.external_transfer ? "질문·제한된 대화·선별 근거 전송" : "외부 전송 없음"}</dd></div>
        </dl>
      </details>
    </aside>
  );
}
