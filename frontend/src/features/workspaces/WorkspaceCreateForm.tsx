import { useId, useRef, useState, type FormEvent } from "react";
import { ApiError } from "../../shared/api/client";
import { createWorkspace, type WorkspaceCreate, type WorkspaceSummary } from "./api";
import styles from "./WorkspaceCreateForm.module.css";

export function WorkspaceCreateForm({ canCreateCompany, onCreated }: {
  canCreateCompany: boolean;
  onCreated: (workspace: WorkspaceSummary) => void;
}) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<WorkspaceCreate["kind"]>("temporary");
  const [expiry, setExpiry] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const pending = useRef(false);
  const expiryHelpId = useId();
  function edited() { setError(""); setSuccess(""); }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current) return;
    setError(""); setSuccess("");
    const trimmedName = name.trim();
    if (!trimmedName || trimmedName.length > 180) {
      setError("공간 이름을 1~180자로 입력해 주세요. 공백만 있는 이름은 사용할 수 없습니다."); return;
    }
    let expiresAt: string | null = null;
    if (kind === "temporary") {
      const date = new Date(expiry);
      if (!Number.isFinite(date.getTime()) || date.getTime() <= Date.now()) {
        setError("임시 공간의 만료 일시는 미래로 지정해 주세요."); return;
      }
      expiresAt = date.toISOString();
    }
    pending.current = true; setSaving(true);
    try {
      const workspace = await createWorkspace({ name: trimmedName, kind, expires_at: expiresAt });
      onCreated(workspace);
      setName(""); setExpiry("");
      setSuccess(`${workspace.name} 공간을 생성했습니다. 아래 목록에서 문서를 관리할 수 있습니다.`);
    } catch (failure) {
      setError(creationError(failure));
    } finally {
      pending.current = false; setSaving(false);
    }
  }
  return <form className={styles.form} aria-label="새 지식 공간 만들기" onSubmit={submit}>
    <h2>새 지식 공간 만들기</h2>
    <p>이름과 유형을 선택한 뒤 ‘공간 만들기’를 눌러 저장합니다. 개인 공간은 사용자당 하나이며, 전사 공간은 소유자만 만들 수 있습니다.</p>
    <fieldset disabled={saving}>
      <label>공간 이름<input value={name} onChange={(event) => { setName(event.target.value); edited(); }} required maxLength={180} /></label>
      <label>새 공간 유형<select value={kind} onChange={(event) => { setKind(event.target.value as WorkspaceCreate["kind"]); edited(); }}>
        {canCreateCompany ? <option value="company">전사</option> : null}
        <option value="personal">개인</option><option value="temporary">임시</option>
      </select></label>
      {kind === "temporary" ? <div><label>만료 일시<input type="datetime-local" value={expiry} aria-describedby={expiryHelpId} onChange={(event) => { setExpiry(event.target.value); edited(); }} required /></label>
        <p id={expiryHelpId} className={styles.help}>현재 기기의 현지 시각 기준으로 미래 일시를 지정해 주세요.</p></div> : null}
    </fieldset>
    <button type="submit" disabled={saving}>{saving ? "생성 중…" : "공간 만들기"}</button>
    {error ? <p role="alert">{error}</p> : null}
    {success ? <p role="status">{success}</p> : null}
  </form>;
}

function creationError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return "로그인이 만료되었을 수 있습니다. 다시 로그인한 뒤 시도해 주세요.";
    if (error.status === 403) return "이 공간을 만들 권한이 없습니다. 계정 권한을 확인해 주세요.";
    if (error.status === 409) return error.code === "personal_workspace_exists"
      ? "개인 공간이 이미 있습니다. 아래 목록의 기존 개인 공간을 이용해 주세요."
      : "기존 공간과 충돌하여 생성하지 못했습니다. 목록을 확인해 주세요.";
    if (error.status === 422) return "공간 이름과 유형, 만료 일시를 확인해 주세요. 전사 공간은 소유자만 만들 수 있습니다.";
  }
  return "공간 생성을 완료하지 못했습니다. 입력을 유지했으니 잠시 후 다시 시도해 주세요.";
}
