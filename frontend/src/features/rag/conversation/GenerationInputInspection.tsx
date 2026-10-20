import type { components } from "../../../shared/api/schema";

export type GenerationInput = components["schemas"]["GenerationInputInspection"];

type JsonObject = Record<string, unknown>;
type Message = { role: string; content: string };
type ParsedInput = { messages: Message[]; question: string; resolvedQuery: string;
  evidence: JsonObject[]; groups: JsonObject[] };

function object(value: unknown): JsonObject | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as JsonObject : null;
}

function parseInput(raw: string): ParsedInput | null {
  try {
    const body = object(JSON.parse(raw));
    if (!body || !Array.isArray(body.messages)) return null;
    const messages: Message[] = [];
    for (const value of body.messages) {
      const message = object(value);
      if (!message || typeof message.role !== "string" || typeof message.content !== "string") return null;
      if (!["system", "user", "assistant", "developer"].includes(message.role)) return null;
      messages.push({ role: message.role, content: message.content });
    }
    const user = messages.filter((message) => message.role === "user").at(-1);
    const payload = user ? object(JSON.parse(user.content)) : null;
    if (!payload || typeof payload.question !== "string" || typeof payload.resolved_query !== "string"
      || !Array.isArray(payload.evidence)) return null;
    const evidence: JsonObject[] = [];
    for (const value of payload.evidence) {
      const item = object(value);
      if (!item || typeof item.evidence_id !== "string" || typeof item.text !== "string") return null;
      evidence.push(item);
    }
    const groups: JsonObject[] = [];
    if (payload.evidence_groups !== undefined) {
      if (!Array.isArray(payload.evidence_groups)) return null;
      for (const value of payload.evidence_groups) {
        const group = object(value);
        if (!group) return null;
        groups.push(group);
      }
    }
    if (evidence.some((item) => item.group_ref !== undefined && (typeof item.group_ref !== "number"
      || !Number.isInteger(item.group_ref) || item.group_ref < 0 || !groups[item.group_ref]))) return null;
    return { messages, question: payload.question, resolvedQuery: payload.resolved_query, evidence, groups };
  } catch {
    return null;
  }
}

const sourceFields = [
  ["group_id", "문맥 ID"], ["document_id", "문서 ID"], ["chunk_id", "청크 ID"],
  ["page", "페이지"], ["source_kind", "원문 종류"], ["source_part", "원문 부분"],
  ["ordinal", "원문 순서"], ["char_start", "시작 위치"], ["char_end", "끝 위치"],
] as const;

function SourceMetadata({ item, group }: { item: JsonObject; group?: JsonObject }) {
  // Inspect only known source fields; never render arbitrary provider object properties.
  const value = (key: string) => Object.hasOwn(item, key) ? item[key] : group?.[key];
  const section = value("section_path");
  const cell = object(value("table_cell"));
  return <div>
    {sourceFields.map(([key, label]) => {
      const field = value(key);
      return typeof field === "string" || typeof field === "number"
        ? <div key={key}>{label}: {field}</div> : null;
    })}
    {Array.isArray(section) && section.every((part) => typeof part === "string")
      ? <div>섹션: {section.join(" / ")}</div> : null}
    {cell && typeof cell.row === "number" && typeof cell.column === "number"
      ? <div>표 셀: 행 {cell.row}, 열 {cell.column}</div> : null}
  </div>;
}

export function GenerationInputInspection({ input }: { input?: GenerationInput | null }) {
  const raw = input?.content_status === "complete" ? input.request_json : null;
  const parsed = raw == null ? null : parseInput(raw);
  return <details className="conversation-evidence">
    <summary>LLM 입력 확인</summary>
    {!input ? <p>이 결과에는 최종 요청 본문 기록이 없습니다. 이전 기록·미지원 실행 경로·생성 미실행일 수 있습니다. 선택된 근거만으로 실제 전송 내용을 복원하지 않습니다.</p> : <>
      <p><strong>{input.status === "response_received"
        ? "HTTP 응답 수신 확인" : "전송 전 준비 입력 · 전송 확인 안 됨"}</strong></p>
      <p>{input.status === "response_received"
        ? "어댑터가 이 요청에 대한 HTTP 응답을 받았습니다. 모델 내부에서 읽거나 이해했는지는 확인할 수 없습니다."
        : "전송 전에 준비한 입력입니다. 이 기록만으로 HTTP 전송이나 모델 수신을 입증하지 않습니다."}</p>
      <p>최종 요청에서 허용된 메시지·옵션만 담은 확인용 JSON입니다. 제공자 내부 모델 ID·헤더·주소는 포함하지 않습니다. SHA-256은 이 확인용 JSON의 해시이며 전체 HTTP 본문 해시나 독립적인 네트워크 전송 증명은 아닙니다. 이 화면의 요청에서만 확인할 수 있으며 새로고침 후에는 보관되지 않습니다.</p>
      <p>제공자: {input.provider} · 방식: {input.dialect} · 등록 모델: {input.model} · 모델 버전: {input.model_version}</p>
      <p>프롬프트: {input.prompt_ref} · 프로파일 버전: {input.profile_version}</p>
      <p>최대 출력 토큰: {input.max_output_tokens} · 제공자 내부 입력 잘림: 확인 불가</p>
      <p>{input.evidence_budget
        ? `근거 문맥 예산: ${input.evidence_budget.max_groups}개 묶음 · ${input.evidence_budget.max_units}개 근거 단위 · ${input.evidence_budget.max_characters}자`
        : "근거 문맥 예산: 미설정"}</p>
      <p>확인용 JSON: {input.body_characters}자 · {input.body_bytes} bytes · 표시용 기록 한도: {input.capture_limit_characters}자</p>
      <p style={{ overflowWrap: "anywhere" }}>확인용 JSON SHA-256: {input.sha256}</p>
      {input.content_status === "omitted_size_limit" ? <p role="status">표시용 기록 한도를 넘어 본문을 보관하지 않았습니다. 실제 요청이 잘렸다는 뜻은 아닙니다. 이 기록에서 원문 조건의 포함 여부는 확인할 수 없습니다.</p>
        : raw == null ? <p role="status">요청 본문을 확인할 수 없습니다.</p> : <>
          {parsed ? <>
            <dl><dt>원래 질문</dt><dd>{parsed.question}</dd><dt>검색에 사용한 질문</dt><dd>{parsed.resolvedQuery}</dd></dl>
            <p>아래는 최종 직렬화 입력에서 읽은 근거입니다. 선택·제외 사유는 검색 후보 표에서 인용 ID와 대조하세요. 근거가 포함되었더라도 필요한 조건이 충분한지, 답변이 이를 반영했는지는 별도로 확인해야 합니다.</p>
            {parsed.evidence.length ? <div style={{ overflowX: "auto" }}><table aria-label="최종 입력 근거">
              <thead><tr><th>인용 ID</th><th>원문 근거</th><th>원문 위치</th></tr></thead>
              <tbody>{parsed.evidence.map((item, index) => <tr key={index}>
                <td>{String(item.evidence_id)}</td>
                <td style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{String(item.text)}</td>
                <td><SourceMetadata item={item} group={typeof item.group_ref === "number" ? parsed.groups[item.group_ref] : undefined} /></td>
              </tr>)}</tbody>
            </table></div> : <p>최종 입력에 근거가 없습니다.</p>}
            <details><summary>최종 지침과 메시지</summary>
              {parsed.messages.map((message, index) => <div key={index}>
                <p>{message.role}</p><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{message.content}</pre>
              </div>)}
            </details>
          </> : <p role="status">입력 형식을 해석할 수 없습니다. 아래 요청 JSON 원문을 확인하세요. 해석 실패를 근거 없음으로 처리하지 않습니다.</p>}
          <details><summary>전송 입력 JSON (허용 필드)</summary>
            <pre aria-label="전송 입력 JSON 허용 필드" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{raw}</pre>
          </details>
        </>}
    </>}
  </details>;
}
