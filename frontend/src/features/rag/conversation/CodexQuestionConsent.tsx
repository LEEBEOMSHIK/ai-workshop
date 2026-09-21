export type CodexClassification = "" | "public" | "synthetic";

export function CodexQuestionConsent({ classification, consented, disabled, onClassification, onConsent }: {
  classification: CodexClassification; consented: boolean; disabled: boolean;
  onClassification: (value: CodexClassification) => void; onConsent: (value: boolean) => void;
}) {
  return <div className="codex-question-consent">
    <label>입력 자료 분류
      <select aria-label="이번 질문과 전송 이력의 분류" value={classification} disabled={disabled} onChange={(event) => { onClassification(event.target.value as CodexClassification); onConsent(false); }}>
        <option value="">직접 확인 후 선택</option><option value="public">공개 자료</option><option value="synthetic">합성 자료</option>
      </select>
    </label>
    <label className="external-question-confirmation"><input type="checkbox" aria-label="이번 질문의 외부 처리를 확인했습니다" checked={consented} disabled={disabled} onChange={(event) => onConsent(event.target.checked)} />이번 질문의 외부 처리·사용량 발생에 동의</label>
    <details><summary>외부 처리 안내</summary>
      <p>현재 질문과 이번 요청에 포함될 이전 대화 전체가 선택한 분류인지 확인하세요. 비공개 자료는 보낼 수 없습니다. 근거 문서는 관리자가 정확한 revision을 별도로 승인해야 합니다.</p>
      <p>관리자가 저장한 전송 승인과 별개로, 매 질문 전에 외부 전송과 계정 사용량 발생에 동의하는 절차입니다.</p>
    </details>
  </div>;
}
