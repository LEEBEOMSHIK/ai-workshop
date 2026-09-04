import { type FormEvent, useState } from "react";

import { ApiError } from "../../../shared/api/client";
import type {
  InstallationDataPolicy,
  WorkspaceDataPolicy,
  WorkspaceSummary,
} from "./api";
import { createInstallationPolicy, createWorkspacePolicy } from "./api";

const providerValue = "openai_responses" as const;

export function DataPolicyPanel({
  installationPolicy: initialInstallation,
  workspaces,
  workspacePolicies: initialWorkspacePolicies,
}: {
  installationPolicy: InstallationDataPolicy;
  workspaces: WorkspaceSummary[];
  workspacePolicies: Record<string, WorkspaceDataPolicy | null>;
}) {
  const [installationPolicy, setInstallationPolicy] = useState(initialInstallation);
  const [workspacePolicies, setWorkspacePolicies] = useState(initialWorkspacePolicies);

  return (
    <section className="data-policy-panel" aria-labelledby="data-policy-title">
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">EXTERNAL DATA POLICY</p>
          <h2 id="data-policy-title">외부 전송 정책</h2>
        </div>
        <p>기존 버전은 바꾸지 않고 강화된 새 버전만 추가합니다.</p>
      </div>
      <InstallationPolicyEditor policy={installationPolicy} onSaved={setInstallationPolicy} />
      <div className="workspace-policy-grid">
        {workspaces.map((workspace) => {
          const policy = workspacePolicies[workspace.id];
          return (
            <WorkspacePolicyEditor
              key={workspace.id}
              workspace={workspace}
              policy={policy ?? null}
              installationPolicy={installationPolicy}
              onSaved={(saved) => setWorkspacePolicies((current) => ({
                ...current,
                [workspace.id]: saved,
              }))}
            />
          );
        })}
      </div>
      {workspaces.length === 0 ? <p role="status">정책을 설정할 지식 공간이 없습니다.</p> : null}
    </section>
  );
}

function InstallationPolicyEditor({
  policy,
  onSaved,
}: {
  policy: InstallationDataPolicy;
  onSaved: (policy: InstallationDataPolicy) => void;
}) {
  const [mode, setMode] = useState<InstallationDataPolicy["mode"]>(policy.mode);
  const [providerApproved, setProviderApproved] = useState(
    policy.approved_providers.includes(providerValue),
  );
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    setError("");
    try {
      const saved = await createInstallationPolicy({
        mode,
        approved_providers: mode === "approved_providers" && providerApproved ? [providerValue] : [],
      });
      onSaved(saved);
      setMessage(`회사 정책 v${saved.version}이 추가되었습니다.`);
    } catch (caught) {
      setError(policyErrorMessage(caught));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="policy-card" onSubmit={handleSubmit}>
      <div className="policy-card-heading"><h3>회사 기본 정책</h3><span>현재 버전 v{policy.version}</span></div>
      <fieldset disabled={saving}>
        <label>회사 외부 전송 정책
          <select value={mode} onChange={(event) => setMode(event.target.value as InstallationDataPolicy["mode"])}>
            <option value="deny">외부 전송 차단</option>
            <option value="approved_providers">승인된 공급자만 허용</option>
          </select>
        </label>
        {mode === "approved_providers" ? (
          <label className="inline-check"><input type="checkbox" checked={providerApproved} onChange={(event) => setProviderApproved(event.target.checked)} />OpenAI Responses API</label>
        ) : null}
      </fieldset>
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      {message ? <p className="form-success" role="status">{message}</p> : null}
      <button type="submit" disabled={saving || (mode === "approved_providers" && !providerApproved)}>{saving ? "추가 중…" : "회사 정책 새 버전 추가"}</button>
    </form>
  );
}

function WorkspacePolicyEditor({
  workspace,
  policy,
  installationPolicy,
  onSaved,
}: {
  workspace: WorkspaceSummary;
  policy: WorkspaceDataPolicy | null;
  installationPolicy: InstallationDataPolicy;
  onSaved: (policy: WorkspaceDataPolicy) => void;
}) {
  const [mode, setMode] = useState<WorkspaceDataPolicy["mode"]>(policy?.mode ?? "inherit");
  const [providerApproved, setProviderApproved] = useState(policy?.approved_providers.includes(providerValue) ?? false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const providerAllowedByInstallation = installationPolicy.mode === "approved_providers"
    && installationPolicy.approved_providers.includes(providerValue);
  const providerSelectionInvalid = mode === "approved_providers" && !providerAllowedByInstallation;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (providerSelectionInvalid) return;
    setSaving(true);
    setMessage("");
    setError("");
    try {
      const saved = await createWorkspacePolicy(workspace.id, {
        mode,
        approved_providers: mode === "approved_providers" && providerApproved ? [providerValue] : [],
      });
      onSaved(saved);
      setMessage(`${workspace.name} 정책 v${saved.version}이 추가되었습니다.`);
    } catch (caught) {
      setError(policyErrorMessage(caught));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="policy-card" role="group" aria-label={`${workspace.name} 외부 전송 정책`} onSubmit={handleSubmit}>
      <div className="policy-card-heading"><h3>{workspace.name}</h3><span>{policy ? `현재 버전 v${policy.version}` : "아직 별도 정책 없음"}</span></div>
      <fieldset disabled={saving}>
        <label>지식 공간 외부 전송 정책
          <select value={mode} onChange={(event) => setMode(event.target.value as WorkspaceDataPolicy["mode"])}>
            <option value="inherit">회사 정책 따름</option>
            <option value="deny">외부 전송 차단</option>
            <option value="approved_providers" disabled={!providerAllowedByInstallation}>승인된 공급자만 허용</option>
          </select>
        </label>
        {mode === "approved_providers" ? (
          <label className="inline-check"><input type="checkbox" checked={providerApproved} onChange={(event) => setProviderApproved(event.target.checked)} />OpenAI Responses API</label>
        ) : null}
      </fieldset>
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      {message ? <p className="form-success" role="status">{message}</p> : null}
      {providerSelectionInvalid ? (
        <p className="form-error" role="status">회사 정책에서 허용하지 않는 공급자입니다. 회사 정책을 따르거나 외부 전송 차단을 선택해 주세요.</p>
      ) : null}
      <button type="submit" disabled={saving || providerSelectionInvalid || (mode === "approved_providers" && !providerApproved)}>{saving ? "추가 중…" : policy ? "정책 새 버전 추가" : "정책 첫 버전 추가"}</button>
    </form>
  );
}

function policyErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return "외부 전송 정책을 추가하지 못했습니다.";
  if (error.status === 401) return "로그인이 필요합니다.";
  if (error.status === 403) return "관리자만 외부 전송 정책을 변경할 수 있습니다.";
  if (error.status === 404) return "지식 공간 또는 현재 정책을 찾을 수 없습니다.";
  if (error.status === 409) return "다른 정책 버전이 먼저 추가되었습니다. 현재 상태를 다시 확인해 주세요.";
  if (error.status === 422) return "정책 값과 상위 정책 범위를 확인해 주세요.";
  return "외부 전송 정책을 추가하지 못했습니다.";
}
