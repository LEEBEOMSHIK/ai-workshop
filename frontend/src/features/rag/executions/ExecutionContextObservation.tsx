import type { Stage } from "./api";
import { AgentStructuredContent } from "./AgentStructuredContent";
import styles from "./ExecutionMonitoring.module.css";

type HistorySelection = NonNullable<Stage["history_selection"]>;
const selectionReasons: Record<HistorySelection["messages"][number]["reason"], string> = {
  selected: "채택", message_limit: "메시지 수 제한으로 제외", token_limit: "토큰 제한으로 제외",
  older_than_token_limit: "더 최근 메시지에서 토큰 한도에 도달해 제외",
};

export function ExecutionContextObservation({ stages }: { stages: Stage[] }) {
  const history = stages.find(stage => stage.stage === "request")?.history_selection;
  const contextualizationStage = stages.find(stage => stage.stage === "contextualization");
  const contextualization = contextualizationStage?.contextualization;
  const retained = contextualization?.content_retention === "retained";
  return <details className={styles.card}>
    <summary>이전 대화 문맥·질문 문맥화</summary>
    <section className={styles.contextSection} aria-label="이전 메시지 선택">
      <h2>실제 채택된 이전 메시지</h2>
      {history ? <>
        <p>준비된 입력 {history.input_message_count}개 메시지 · 실제 채택 {history.selected_message_count}개 메시지</p>
        <p className={styles.hint}>적용 한도: 최대 {history.max_history_messages}개 메시지 · {history.max_history_tokens}토큰. 질문과 답변은 각각 별도 메시지입니다.</p>
        <p className={styles.hint}>최종 문맥 정책에 전달된 최대 20개 메시지에 대한 기록입니다. 준비 전 제외 내역은 포함하지 않습니다. 일반 대화는 현재 권한·대화 구간·완료·서명 확인을 거쳐 준비하며, 출처 턴이 없는 이력의 준비 경로는 이 기록만으로 확인할 수 없습니다. 채택 여부는 답변 품질 평가가 아닙니다.</p>
        {history.messages.length ? <ol className={styles.historyMessages}>
          {history.messages.map(message => <li key={message.position} data-selected={message.selected}>
            <p><strong>메시지 {message.position + 1} · {message.role === "user" ? "사용자" : "어시스턴트"}</strong></p>
            <p>{selectionReasons[message.reason]}</p>
            {message.conversation_turn_id ? <details><summary>출처 턴 식별자</summary><code className={styles.identifier}>{message.conversation_turn_id}</code></details>
              : <p className={styles.hint}>출처 턴 미기록</p>}
          </li>)}
        </ol> : <p>준비된 이전 메시지가 없습니다.</p>}
      </> : <p>이전 메시지 선택 미기록</p>}
    </section>
    <section className={styles.contextSection} aria-label="질문 문맥화 기록">
      <h2>질문 문맥화 기록</h2>
      {contextualization ? <>
        <p className={styles.hint}>질문 문맥화의 실제 HTTP 요청 본문과 최종 응답입니다. SDK 답변 생성 단계와 구분한 관측이며 모델의 비공개 내부 추론을 포함하지 않습니다.</p>
        {!contextualization.observation_complete ? <p>문맥화 관측 기록이 불완전합니다.</p> : null}
        {contextualization.truncated ? <p>보관 한도로 일부 본문을 생략했습니다. 실제 모델 입력이나 결과가 잘렸다는 뜻은 아닙니다.</p> : null}
        <div className={styles.contextBodies}>
          <AgentStructuredContent title="문맥화 지침" content={contextualization.instructions} showCompleteBody={retained} validationContext="observation" />
          <AgentStructuredContent title="문맥화 HTTP 입력" content={contextualization.input} showCompleteBody={retained} validationContext="observation" />
          <AgentStructuredContent title="문맥화 최종 응답" content={contextualization.output} showCompleteBody={retained} validationContext="observation" />
        </div>
      </> : contextualizationStage?.state === "skipped" ? <p>이 실행에서는 질문 문맥화를 생략했습니다.</p>
        : <p>질문 문맥화 본문 미기록</p>}
    </section>
    {!history || !contextualization ? <p className={styles.hint}>과거 실행의 문맥 선택과 요청·응답을 복원하지 않습니다.</p> : null}
  </details>;
}
