"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { executionPath } from "../../../shared/routing/routes";
import { getConversation, type ConversationDetail } from "../conversation/sessions-api";
import styles from "./ExecutionMonitoring.module.css";

type Props = { domainSlug: string; conversationId: string; executionId: string; turnId?: string | null };

export function ExecutionConversationTurns(props: Props) {
  return <ConversationTurns key={`${props.domainSlug}:${props.conversationId}:${props.executionId}`} {...props} />;
}

function ConversationTurns({ domainSlug, conversationId, executionId, turnId }: Props) {
  const [conversation, setConversation] = useState<ConversationDetail | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    getConversation(domainSlug, conversationId, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      if (value.id !== conversationId) throw new Error("Conversation identity mismatch");
      setConversation(value);
    }).catch(() => {
      if (controller.signal.aborted) return;
      setConversation(null);
      setError(true);
    });
    return () => controller.abort();
  }, [domainSlug, conversationId, attempt]);
  function retry() {
    setConversation(null);
    setError(false);
    setAttempt(value => value + 1);
  }
  const turns = conversation ? [...conversation.turns].sort((left, right) => left.sequence - right.sequence) : undefined;
  const isCurrent = (id: string, linkedExecution?: string | null) => turnId
    ? id === turnId && (linkedExecution == null || linkedExecution === executionId)
    : linkedExecution === executionId;
  const currentFound = turns?.some(turn => !turn.redacted && isCurrent(turn.id, turn.execution_id));
  return <nav aria-label="같은 대화의 턴" className={styles.card}>
    <h2>같은 대화의 턴</h2>
    <p className={styles.hint}>질문을 선택하면 연결된 실행으로 이동합니다. 구간은 검색 범위가 이어지는 대화의 구분이며, 이 목록 전체가 모델에 사용된 문맥은 아닙니다.</p>
    {error ? <p role="alert">대화 턴을 열 수 없습니다. 삭제되었거나 현재 접근 권한이 없을 수 있습니다. <button type="button" onClick={retry}>대화 턴 다시 조회</button></p> : null}
    {!conversation && !error ? <p role="status">대화 턴을 불러오고 있습니다…</p> : null}
    {turns?.length ? <>
      {!currentFound ? <p className={styles.hint}>현재 실행에 연결된 턴을 확인할 수 없습니다.</p> : null}
      <ol className={styles.conversationTurns}>
        {turns.map(turn => {
          const current = !turn.redacted && isCurrent(turn.id, turn.execution_id);
          const content = <><span className={styles.turnMeta}>{turn.sequence}번 질문 · 구간 {turn.segment}{current ? <strong>현재 실행</strong> : null}</span>
            <span>{turn.redacted ? "현재 권한으로 볼 수 없는 질문" : turn.query}</span>
            {!turn.redacted && !turn.execution_id ? <small>연결된 실행 기록 없음</small> : null}</>;
          return <li key={turn.id} data-current={current || undefined}>
            {!turn.redacted && turn.execution_id ? <Link href={executionPath(turn.execution_id)} aria-current={current ? "page" : undefined}>{content}</Link>
              : <div className={styles.unlinkedTurn} aria-current={current ? "step" : undefined}>{content}</div>}
          </li>;
        })}
      </ol>
    </> : conversation ? <p>표시할 대화 턴이 없습니다.</p> : null}
  </nav>;
}
