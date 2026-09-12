import { type FormEvent, useState } from "react";

import { ApiError } from "../../../shared/api/client";
import type {
  InstallationDataPolicy,
  WorkspaceDataPolicy,
  WorkspaceSummary,
} from "./api";
import { createInstallationPolicy, createWorkspacePolicy } from "./api";

type Provider = InstallationDataPolicy["approved_providers"][number];
const providerLabels: Record<Provider, string> = { local_openai_compatible: "로컬 OpenAI 호환", openai_responses: "OpenAI Responses API", development_codex_exec: "개발용 Codex CLI" };
function ProviderChoices({ selected, onChange, allowed }: { selected: Provider[]; onChange: (next: Provider[]) => void; allowed?: Provider[] }) {
  return <>{(Object.keys(providerLabels) as Provider[]).map((provider) => <label className="inline-check" key={provider}><input type="checkbox" checked={selected.includes(provider)} disabled={allowed !== undefined && !allowed.includes(provider) && !selected.includes(provider)} onChange={(event) => onChange(event.target.checked ? [...selected, provider] : selected.filter((item) => item !== provider))} />{providerLabels[provider]}</label>)}</>;
}

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
        <p>선택만으로는 저장되지 않습니다. 정책 저장을 누르면 기존 버전을 유지하고 새 불변 버전으로 저장합니다.</p>
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
  const [providers, setProviders] = useState<Provider[]>(policy.approved_providers);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const dirty = !matchesSavedPolicy(mode, providers, policy);
  const invalid = mode === "approved_providers" && !providers.length;
  function edited() { setMessage(""); setError(""); }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving || !dirty || invalid) return;
    setSaving(true);
    setMessage("");
    setError("");
    try {
      const saved = await createInstallationPolicy({
        mode,
        approved_providers: mode === "approved_providers" ? providers : [],
      });
      onSaved(saved);
      setMode(saved.mode);
      setProviders(saved.approved_providers);
      setMessage(`회사 정책 v${saved.version}이 저장되었습니다.`);
    } catch (caught) {
      setError(policyErrorMessage(caught));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="policy-card" aria-label="회사 기본 외부 전송 정책" onSubmit={handleSubmit}>
      <div className="policy-card-heading"><h3>회사 기본 정책</h3><span>현재 버전 v{policy.version}</span></div>
      <fieldset disabled={saving}>
        <label>회사 외부 전송 정책
          <select value={mode} onChange={(event) => { edited(); setMode(event.target.value as InstallationDataPolicy["mode"]); }}>
            <option value="deny">외부 전송 차단</option>
            <option value="approved_providers">승인된 공급자만 허용</option>
          </select>
        </label>
        {mode === "approved_providers" ? (
          <ProviderChoices selected={providers} onChange={(next) => { edited(); setProviders(next); }} />
        ) : null}
      </fieldset>
      {error ? <p className="form-error" role="alert">정책을 저장하지 못했습니다. {error}</p> : null}
      <p className={message ? "form-success" : "control-help"} role="status">{saving ? "저장 중…" : message || (dirty ? "저장하지 않은 변경사항이 있습니다." : "저장된 정책과 같습니다.")}</p>
      <button type="submit" aria-label="회사 기본 정책 저장" disabled={saving || !dirty || invalid}>{saving ? "저장 중…" : "정책 저장"}</button>
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
  const [providers, setProviders] = useState<Provider[]>(policy?.approved_providers ?? []);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const allowed = installationPolicy.mode === "approved_providers" ? installationPolicy.approved_providers : [];
  const providerAllowedByInstallation = allowed.length > 0;
  const providerSelectionInvalid = mode === "approved_providers" && (!providerAllowedByInstallation || providers.some((provider) => !allowed.includes(provider)));
  const dirty = !matchesSavedPolicy(mode, providers, policy);
  const invalid = providerSelectionInvalid || (mode === "approved_providers" && !providers.length);
  function edited() { setMessage(""); setError(""); }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving || !dirty || invalid) return;
    setSaving(true);
    setMessage("");
    setError("");
    try {
      const saved = await createWorkspacePolicy(workspace.id, {
        mode,
        approved_providers: mode === "approved_providers" ? providers : [],
      });
      onSaved(saved);
      setMode(saved.mode);
      setProviders(saved.approved_providers);
      setMessage(`${workspace.name} 정책 v${saved.version}이 저장되었습니다.`);
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
          <select value={mode} onChange={(event) => { edited(); setMode(event.target.value as WorkspaceDataPolicy["mode"]); }}>
            <option value="inherit">회사 정책 따름</option>
            <option value="deny">외부 전송 차단</option>
            <option value="approved_providers" disabled={!providerAllowedByInstallation}>승인된 공급자만 허용</option>
          </select>
        </label>
        {mode === "approved_providers" ? (
          <ProviderChoices selected={providers} onChange={(next) => { edited(); setProviders(next); }} allowed={allowed} />
        ) : null}
      </fieldset>
      {error ? <p className="form-error" role="alert">정책을 저장하지 못했습니다. {error}</p> : null}
      <p className={message ? "form-success" : "control-help"} role="status">{saving ? "저장 중…" : message || (dirty ? "저장하지 않은 변경사항이 있습니다." : "저장된 정책과 같습니다.")}</p>
      {providerSelectionInvalid ? (
        <p className="form-error" role="status">회사 정책에서 허용하지 않는 공급자입니다. 회사 정책을 따르거나 외부 전송 차단을 선택해 주세요.</p>
      ) : null}
      <button type="submit" aria-label={`${workspace.name} 정책 저장`} disabled={saving || !dirty || invalid}>{saving ? "저장 중…" : "정책 저장"}</button>
    </form>
  );
}

function matchesSavedPolicy(mode: WorkspaceDataPolicy["mode"], providers: Provider[], saved: Pick<WorkspaceDataPolicy, "mode" | "approved_providers"> | null): boolean {
  if (!saved || mode !== saved.mode) return false;
  if (mode !== "approved_providers") return true;
  const current = new Set(providers);
  const baseline = new Set(saved.approved_providers);
  return current.size === baseline.size && [...current].every((provider) => baseline.has(provider));
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
