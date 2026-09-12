import { useEffect, useId, useRef, useState } from "react";
import { workspaceLibraryPath } from "../../../shared/routing/routes";
import {
  approveCodexEvidence,
  codexError,
  isCodexEvidenceConflict,
  loadCodexEvidence,
  revokeCodexEvidence,
  type CodexEvidence,
  type WorkspaceSummary,
} from "./api";

type ApprovalClassification = "public" | "synthetic";
type PendingMutation =
  | { action: "approve"; request: Parameters<typeof approveCodexEvidence>[1] }
  | { action: "revoke"; request: Parameters<typeof revokeCodexEvidence>[1] };

export function CodexEvidenceApproval({ workspaces }: { workspaces: WorkspaceSummary[] }) {
  const [workspace, setWorkspace] = useState(workspaces[0]?.id ?? "");
  const [items, setItems] = useState<CodexEvidence[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const sequence = useRef(0);
  const selectedWorkspace = useRef(workspace);

  useEffect(() => () => { sequence.current++; }, []);

  async function load(): Promise<boolean> {
    if (selectedWorkspace.current !== workspace) return false;
    const current = ++sequence.current;
    setBusy(true);
    setError("");
    try {
      const data = await loadCodexEvidence(workspace);
      if (sequence.current !== current) return false;
      setItems(data);
      return true;
    } catch (failure) {
      if (sequence.current === current) setError(codexError(failure));
      throw failure;
    } finally {
      if (sequence.current === current) setBusy(false);
    }
  }

  return <section className="registry-panel">
    <h3>Codex 외부 전송 자료 승인</h3>
    <p>업로드는 자동 승인되지 않습니다. 원문을 직접 확인한 공개·합성 자료의 정확한 버전만 승인하세요. 승인만으로 모델이 실행되지는 않습니다.</p>
    <label>자료 지식 공간
      <select value={workspace} disabled={busy} onChange={(event) => {
        sequence.current++;
        selectedWorkspace.current = event.target.value;
        setWorkspace(event.target.value);
        setItems([]);
        setError("");
      }}>
        {workspaces.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select>
    </label>
    <button type="button" disabled={!workspace || busy} onClick={() => void load().catch(() => undefined)}>문서 revision 불러오기</button>
    {busy ? <p role="status">자료를 불러오는 중…</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    {items.map((item) => <EvidenceRow key={`${workspace}-${item.revision_id}`} item={item} onChanged={load} />)}
  </section>;
}

function EvidenceRow({ item, onChanged }: { item: CodexEvidence; onChanged: () => Promise<boolean> }) {
  const classificationHelpId = useId();
  const [classification, setClassification] = useState<"" | ApprovalClassification>("");
  const [approvalConfirmed, setApprovalConfirmed] = useState(false);
  const [revocationConfirmed, setRevocationConfirmed] = useState(false);
  const [pending, setPending] = useState<PendingMutation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [requiresRefresh, setRequiresRefresh] = useState(false);
  const observedGeneration = useRef(item.approval_generation);
  const active = item.approval_classification !== null && !item.revoked;

  useEffect(() => {
    if (observedGeneration.current === item.approval_generation) return;
    observedGeneration.current = item.approval_generation;
    setClassification("");
    setApprovalConfirmed(false);
    setRevocationConfirmed(false);
    setPending(null);
    setRequiresRefresh(false);
  }, [item.approval_generation]);

  async function mutate(action: "approve" | "revoke") {
    if (busy || requiresRefresh) return;
    if (action === "approve" && (active || !classification || !approvalConfirmed)) return;
    if (action === "revoke" && (!active || !revocationConfirmed)) return;

    const command: PendingMutation = pending?.action === action
      ? pending
      : action === "approve"
        ? {
            action,
            request: {
              classification: classification as ApprovalClassification,
              content_sha256: item.content_sha256,
              expected_generation: item.approval_generation,
              request_id: crypto.randomUUID(),
            },
          }
        : {
            action,
            request: {
              expected_generation: item.approval_generation,
              request_id: crypto.randomUUID(),
            },
          };
    setPending(command);
    setBusy(true);
    setError("");
    setMessage("");

    try {
      if (command.action === "approve") await approveCodexEvidence(item.revision_id, command.request);
      else await revokeCodexEvidence(item.revision_id, command.request);
    } catch (failure) {
      if (!isCodexEvidenceConflict(failure)) {
        setError(codexError(failure));
        setBusy(false);
        return;
      }

      setPending(null);
      setClassification("");
      setApprovalConfirmed(false);
      setRevocationConfirmed(false);
      try {
        const refreshed = await onChanged();
        if (refreshed) setError("다른 변경이 먼저 저장되어 최신 상태를 다시 불러왔습니다. 자료 분류와 동의를 다시 확인해 주세요.");
      } catch {
        setRequiresRefresh(true);
        setError("다른 변경이 먼저 저장되었고 최신 상태를 다시 불러오지 못했습니다. 문서 상태를 다시 불러온 뒤 새로 동의해 주세요.");
      } finally {
        setBusy(false);
      }
      return;
    }

    setPending(null);
    setClassification("");
    setApprovalConfirmed(false);
    setRevocationConfirmed(false);
    try {
      await onChanged();
    } catch {
      setRequiresRefresh(true);
      setMessage(`${action === "approve" ? "승인" : "승인 취소"} 요청은 완료되었지만 최신 상태를 불러오지 못했습니다. 상태를 다시 조회하기 전에는 추가 변경을 할 수 없습니다.`);
    } finally {
      setBusy(false);
    }
  }

  async function retryRefresh() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const refreshed = await onChanged();
      if (refreshed) {
        setRequiresRefresh(false);
        setMessage("");
        setClassification("");
        setApprovalConfirmed(false);
        setRevocationConfirmed(false);
        setPending(null);
      }
    } catch (failure) {
      setError(`최신 문서 상태를 다시 불러오지 못했습니다. ${codexError(failure)}`);
    } finally {
      setBusy(false);
    }
  }

  const mutationInFlight = busy && pending !== null;
  const status = mutationInFlight
    ? pending.action === "approve" ? "승인 처리 중" : "승인 취소 처리 중"
    : active ? "승인됨" : item.revoked ? "승인 취소" : "미승인";
  const approveLabel = mutationInFlight && pending.action === "approve"
    ? "승인 처리 중…"
    : pending?.action === "approve"
      ? "동일 승인 요청 다시 시도"
    : item.revoked ? "다시 승인" : "외부 전송 자료 승인";

  return <article className="saved-configuration-card">
    <h4>{item.document_name} · revision {item.revision_number}</h4>
    <p>상태: {status} · 승인 세대 {item.approval_generation}</p>
    <p>대상 공급자: Codex CLI (<code>{item.provider}</code>)</p>
    <p><a href={workspaceLibraryPath(item.workspace_id, { documentId: item.document_id, versionId: item.revision_id })}>이 버전 원문 확인</a></p>
    <details>
      <summary>기술 식별자와 해시</summary>
      <p>revision ID: <code>{item.revision_id}</code></p>
      <p>document ID: <code>{item.document_id}</code></p>
      <p>SHA-256: <code>{item.content_sha256}</code></p>
    </details>
    <details>
      <summary>승인 이력 ({item.approval_history.length}건)</summary>
      <p>{item.document_name} revision {item.revision_number} · {item.provider}</p>
      {item.approval_history.length === 0 ? <p>기록된 승인 이력이 없습니다.</p> : <ol>
        {item.approval_history.map((entry) => <li key={entry.generation}>
          {entry.action === "approve" ? "승인" : "승인 취소"} · 세대 {entry.generation} · {classificationLabel(entry.classification)} · 처리 주체 {entry.actor_id ?? "미기록"} · <time dateTime={entry.occurred_at}>{formatOccurredAt(entry.occurred_at)}</time>
        </li>)}
      </ol>}
    </details>

    {active ? <>
      <p>승인 분류: {classificationLabel(item.approval_classification as ApprovalClassification)}</p>
      <label><input type="checkbox" checked={revocationConfirmed} disabled={busy || requiresRefresh} onChange={(event) => setRevocationConfirmed(event.target.checked)} />승인을 취소해도 이미 전송된 자료는 회수되지 않음을 확인했습니다.</label>
      <button type="button" disabled={busy || requiresRefresh || !revocationConfirmed} onClick={() => void mutate("revoke")}>
        {mutationInFlight && pending.action === "revoke"
          ? "승인 취소 처리 중…"
          : pending?.action === "revoke" ? "동일 승인 취소 요청 다시 시도" : "이 revision 승인 취소"}
      </button>
    </> : <>
      <label>자료 분류
        <select aria-describedby={classificationHelpId} value={classification} disabled={busy || requiresRefresh} onChange={(event) => {
          setClassification(event.target.value as typeof classification);
          setApprovalConfirmed(false);
          setPending(null);
          setError("");
        }}>
          <option value="">직접 확인 후 선택</option>
          <option value="public">공개 자료</option>
          <option value="synthetic">합성 자료</option>
        </select>
      </label>
      <label><input type="checkbox" checked={approvalConfirmed} disabled={busy || requiresRefresh || !classification} onChange={(event) => setApprovalConfirmed(event.target.checked)} />선택한 자료 분류와 원문을 확인했으며 이 버전의 대상 공급자 외부 전송에 동의합니다.</label>
      <button type="button" disabled={busy || requiresRefresh || !classification || !approvalConfirmed} onClick={() => void mutate("approve")}>{approveLabel}</button>
    </>}
    <div id={classificationHelpId} className="control-help">
      <p>공개 자료: 이미 공개되어 있으며, 대상 공급자로 외부 전송해도 되는지 확인한 자료입니다.</p>
      <p>합성 자료: 실제 개인정보·기밀 등 민감정보가 없는 가상·테스트 자료입니다. AI가 만든 자료만을 뜻하지 않습니다.</p>
      <p>공개된 합성 자료처럼 두 분류에 모두 해당하면 합성 자료를 선택하세요.</p>
      <p>분류 선택이나 승인은 원문을 자동으로 익명화하거나 사이트에 공개하지 않으며, AI를 자동 실행하지 않습니다.</p>
    </div>

    {message ? <p role="status">{message}</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    {requiresRefresh ? <button type="button" disabled={busy} onClick={() => void retryRefresh()}>문서 상태 다시 불러오기</button> : null}
  </article>;
}

function classificationLabel(classification: ApprovalClassification): string {
  return classification === "public" ? "공개" : "합성";
}

function formatOccurredAt(value: string): string {
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime()) ? value : timestamp.toLocaleString("ko-KR");
}
